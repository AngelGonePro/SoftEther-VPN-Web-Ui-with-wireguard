#!/bin/bash
# Windscribe routing setup script
# Routes WireGuard (10.13.13.0/24) and SoftEther OpenVPN (192.168.30.0/24)
# through Windscribe VPN using veth pair to windscribe namespace

set -e
log() { echo "[windscribe-routing] $*"; }

# Wait for windscribe-gw to be running
log "Waiting for windscribe-gw..."
for i in $(seq 1 60); do
    WSPID=$(docker inspect windscribe-gw --format '{{.State.Pid}}' 2>/dev/null)
    [ -n "$WSPID" ] && [ "$WSPID" != "0" ] && break
    sleep 2
done
if [ -z "$WSPID" ] || [ "$WSPID" = "0" ]; then
    log "ERROR: windscribe-gw not running after 120s"
    exit 1
fi
log "windscribe-gw PID: $WSPID"

# Wait for utun420 inside windscribe namespace
log "Waiting for utun420..."
for i in $(seq 1 30); do
    nsenter -t $WSPID -n ip link show utun420 &>/dev/null && break
    sleep 2
done

# Create netns symlink
mkdir -p /var/run/netns
ln -sf /proc/$WSPID/ns/net /var/run/netns/windscribe
log "Created netns symlink"

# Create veth pair if not exists
if ! ip link show veth-ws-host &>/dev/null; then
    log "Creating veth pair..."
    ip link add veth-ws-host type veth peer name veth-ws-gw
    ip link set veth-ws-gw netns windscribe
    ip addr add 192.168.255.1/30 dev veth-ws-host
    ip link set veth-ws-host up
    ip netns exec windscribe ip addr add 192.168.255.2/30 dev veth-ws-gw
    ip netns exec windscribe ip link set veth-ws-gw up
    log "veth pair created"
else
    log "veth pair already exists"
fi

# Set MTU
ip link set veth-ws-host mtu 1300 2>/dev/null || true

# Enable proxy ARP
echo 1 > /proc/sys/net/ipv4/conf/veth-ws-host/proxy_arp

# Host policy routing
ip rule show | grep -q "from 10.13.13.0/24 lookup 400" || \
    ip rule add from 10.13.13.0/24 table 400 priority 50
ip rule show | grep -q "from 192.168.30.0/24 lookup 400" || \
    ip rule add from 192.168.30.0/24 table 400 priority 51
ip rule show | grep -q "fwmark 0x3 lookup 400" || \
    ip rule add fwmark 0x3 table 400 priority 45
ip route replace default via 192.168.255.2 dev veth-ws-host table 400

# Host route: WireGuard replies via wg0
ip route show | grep -q "^10.13.13.0/24 dev wg0" || \
    ip route add 10.13.13.0/24 dev wg0 2>/dev/null || true

# Host route: SoftEther replies via vpn-net bridge (Docker network ID survives reboots)
SE_BRIDGE=$(docker network inspect softether-vpn_vpn-net --format '{{.Id}}' | cut -c1-12)
ip route show | grep -q "^192.168.30.0/24" && \
    ip route replace 192.168.30.0/24 dev br-$SE_BRIDGE 2>/dev/null || \
    ip route add 192.168.30.0/24 dev br-$SE_BRIDGE 2>/dev/null || true

log "Host routing configured"

# SoftEther OpenVPN: mark NEW outbound connections to route through Windscribe
SE_IP=$(docker inspect softether --format \
    '{{(index .NetworkSettings.Networks "softether-vpn_vpn-net").IPAddress}}' 2>/dev/null)
if [ -n "$SE_IP" ] && [ -n "$SE_BRIDGE" ]; then
    iptables -t mangle -C PREROUTING -s $SE_IP -i br-$SE_BRIDGE \
        -m conntrack --ctstate NEW -j MARK --set-mark 0x3 2>/dev/null || \
        iptables -t mangle -A PREROUTING -s $SE_IP -i br-$SE_BRIDGE \
        -m conntrack --ctstate NEW -j MARK --set-mark 0x3
    iptables -t mangle -C PREROUTING -s $SE_IP -i br-$SE_BRIDGE \
        -m conntrack --ctstate ESTABLISHED,RELATED -j CONNMARK --restore-mark 2>/dev/null || \
        iptables -t mangle -A PREROUTING -s $SE_IP -i br-$SE_BRIDGE \
        -m conntrack --ctstate ESTABLISHED,RELATED -j CONNMARK --restore-mark
    log "SoftEther OpenVPN mangle rules set for $SE_IP"
fi

# Windscribe namespace setup
ip netns exec windscribe sysctl -w net.ipv4.ip_forward=1 &>/dev/null

# Remove old DROP rules
ip netns exec windscribe iptables -D FORWARD -s 10.13.13.0/24 -o utun420 -j DROP 2>/dev/null || true
ip netns exec windscribe iptables -D FORWARD -s 192.168.30.0/24 -o utun420 -j DROP 2>/dev/null || true

# Route VPN subnets to utun420
ip netns exec windscribe ip rule show | grep -q "from 10.13.13.0/24 lookup 51820" || \
    ip netns exec windscribe ip rule add from 10.13.13.0/24 table 51820 priority 46
ip netns exec windscribe ip rule show | grep -q "from 192.168.30.0/24 lookup 51820" || \
    ip netns exec windscribe ip rule add from 192.168.30.0/24 table 51820 priority 47
ip netns exec windscribe ip route replace default dev utun420 table 51820

# Route replies back to host via veth
ip netns exec windscribe ip route show | grep -q "^10.13.13.0/24" || \
    ip netns exec windscribe ip route add 10.13.13.0/24 dev veth-ws-gw
ip netns exec windscribe ip route show | grep -q "^192.168.30.0/24" || \
    ip netns exec windscribe ip route add 192.168.30.0/24 dev veth-ws-gw 2>/dev/null || true

# Static ARP
VETH_MAC=$(cat /sys/class/net/veth-ws-host/address)
ip netns exec windscribe ip neigh replace 10.13.13.1 dev veth-ws-gw lladdr $VETH_MAC 2>/dev/null || true
ip netns exec windscribe ip neigh replace 10.13.13.2 dev veth-ws-gw lladdr $VETH_MAC 2>/dev/null || true
ip netns exec windscribe ip neigh replace 192.168.30.1 dev veth-ws-gw lladdr $VETH_MAC 2>/dev/null || true

# MASQUERADE in windscribe namespace
ip netns exec windscribe iptables -t nat -C POSTROUTING -s 10.13.13.0/24 -o utun420 -j MASQUERADE 2>/dev/null || \
    ip netns exec windscribe iptables -t nat -A POSTROUTING -s 10.13.13.0/24 -o utun420 -j MASQUERADE
ip netns exec windscribe iptables -t nat -C POSTROUTING -s 192.168.30.0/24 -o utun420 -j MASQUERADE 2>/dev/null || \
    ip netns exec windscribe iptables -t nat -A POSTROUTING -s 192.168.30.0/24 -o utun420 -j MASQUERADE

# FORWARD rules
ip netns exec windscribe iptables -C FORWARD -s 10.13.13.0/24 -o utun420 -j ACCEPT 2>/dev/null || \
    ip netns exec windscribe iptables -A FORWARD -s 10.13.13.0/24 -o utun420 -j ACCEPT
ip netns exec windscribe iptables -C FORWARD -i utun420 -d 10.13.13.0/24 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
    ip netns exec windscribe iptables -A FORWARD -i utun420 -d 10.13.13.0/24 -m state --state ESTABLISHED,RELATED -j ACCEPT
ip netns exec windscribe iptables -C FORWARD -s 192.168.30.0/24 -o utun420 -j ACCEPT 2>/dev/null || \
    ip netns exec windscribe iptables -A FORWARD -s 192.168.30.0/24 -o utun420 -j ACCEPT
ip netns exec windscribe iptables -C FORWARD -i utun420 -d 192.168.30.0/24 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
    ip netns exec windscribe iptables -A FORWARD -i utun420 -d 192.168.30.0/24 -m state --state ESTABLISHED,RELATED -j ACCEPT

log "Windscribe namespace routing configured"
log "Done! WireGuard and OpenVPN client traffic will route through Windscribe."

# MTU/MSS fix for double-tunneling
WSPID=$(docker inspect windscribe-gw --format '{{.State.Pid}}' 2>/dev/null)
if [ -n "$WSPID" ] && [ "$WSPID" != "0" ]; then
    nsenter -t $WSPID -n ip link set utun420 mtu 1350 2>/dev/null || true
    nsenter -t $WSPID -n iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN \
        -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
    nsenter -t $WSPID -n iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
        -j TCPMSS --clamp-mss-to-pmtu
fi
iptables -t mangle -C FORWARD -s 172.21.0.3 -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
iptables -t mangle -A FORWARD -s 172.21.0.3 -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu
iptables -t mangle -C FORWARD -d 172.21.0.3 -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
iptables -t mangle -A FORWARD -d 172.21.0.3 -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu

# SoftEther routing setup
# - Default route via windscribe-gw so VPN clients get Windscribe IP
# - fwmark 0x4 marks inbound packets so replies go direct (required for policy routing)
# - fwmark 0x5 marks VPN port replies to go direct
# - VPS local and public IPs route direct
SE_IP=$(docker inspect softether --format \
    '{{(index .NetworkSettings.Networks "softether-vpn_vpn-net").IPAddress}}' 2>/dev/null)
if [ -n "$SE_IP" ]; then
    # Default route through windscribe-gw
    docker exec softether ip route replace default via 172.21.0.2 dev eth0 2>/dev/null || true
    # VPS local and public IPs go direct
    docker exec softether ip route show | grep -q "192.168.128.0/17" || \
        docker exec softether ip route add 192.168.128.0/17 via 172.21.0.1 dev eth0 2>/dev/null || true
    docker exec softether ip route show | grep -q "45.79.25.46/32" || \
        docker exec softether ip route add 45.79.25.46/32 via 172.21.0.1 dev eth0 2>/dev/null || true
    # Table 100: direct routing for inbound replies
    docker exec softether ip route show table 100 2>/dev/null | grep -q "^default" || \
        docker exec softether ip route add default via 172.21.0.1 dev eth0 table 100 2>/dev/null || true
    docker exec softether ip route show table 100 2>/dev/null | grep -q "192.168.128.0/17" || \
        docker exec softether ip route add 192.168.128.0/17 via 172.21.0.1 dev eth0 table 100 2>/dev/null || true
    # fwmark rules
    docker exec softether ip rule show 2>/dev/null | grep -q "fwmark 0x4" || \
        docker exec softether ip rule add fwmark 0x4 table 100 priority 40 2>/dev/null || true
    docker exec softether ip rule show 2>/dev/null | grep -q "fwmark 0x5" || \
        docker exec softether ip rule add fwmark 0x5 table 100 priority 39 2>/dev/null || true
    # Mark inbound packets to SoftEther (required for UniFi policy routing to work)
    docker exec softether iptables -t mangle -C PREROUTING \
        -d $SE_IP -j MARK --set-mark 0x4 2>/dev/null || \
        docker exec softether iptables -t mangle -A PREROUTING \
        -d $SE_IP -j MARK --set-mark 0x4 2>/dev/null || true
    # Mark VPN port replies to go direct
    docker exec softether iptables -t mangle -C OUTPUT \
        -p udp --sport 1194 -j MARK --set-mark 0x5 2>/dev/null || \
        docker exec softether iptables -t mangle -A OUTPUT \
        -p udp --sport 1194 -j MARK --set-mark 0x5 2>/dev/null || true
    docker exec softether iptables -t mangle -C OUTPUT \
        -p tcp --sport 443 -j MARK --set-mark 0x5 2>/dev/null || \
        docker exec softether iptables -t mangle -A OUTPUT \
        -p tcp --sport 443 -j MARK --set-mark 0x5 2>/dev/null || true
    log "SoftEther inbound routing rules set"
fi
