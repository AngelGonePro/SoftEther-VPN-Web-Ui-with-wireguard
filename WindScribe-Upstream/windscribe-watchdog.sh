#!/bin/bash
# Windscribe watchdog - run by systemd timer every 60 seconds

# Check if windscribe-gw container is running
WSPID=$(docker inspect windscribe-gw --format '{{.State.Pid}}' 2>/dev/null)
if [ -z "$WSPID" ] || [ "$WSPID" = "0" ]; then
    cd /root/windscribe-gw && docker compose up -d
    sleep 50
    systemctl restart windscribe-routing.service
    exit 0
fi

# Find gateway interface by IP subnet (not eth name - survives reboots)
GW_IFACE=$(docker exec windscribe-gw ip -o addr show 2>/dev/null | awk '/10\.200\.0\./ {print $2}')
GW="10.200.0.1"

# Check if utun420 is up
if ! nsenter -t $WSPID -n ip link show utun420 &>/dev/null; then
    docker exec windscribe-gw ip route add default via $GW dev $GW_IFACE 2>/dev/null || true
    docker exec windscribe-gw su - wsuser -c \
        'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus && windscribe-cli connect Ranch wireguard' 2>/dev/null
    sleep 15
    systemctl restart windscribe-routing.service
    exit 0
fi

# Check internet through tunnel
if ! nsenter -t $WSPID -n ping -c 1 -W 3 -I utun420 8.8.8.8 &>/dev/null; then
    docker exec windscribe-gw ip route add default via $GW dev $GW_IFACE 2>/dev/null || true
    docker exec windscribe-gw su - wsuser -c \
        'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus && windscribe-cli connect Ranch wireguard' 2>/dev/null
    exit 0
fi

# Check veth still exists
if ! ip link show veth-ws-host &>/dev/null; then
    systemctl restart windscribe-routing.service
    exit 0
fi

# Fix SoftEther 192.168.30 route if wrong bridge
SE_BRIDGE=$(docker network inspect softether-vpn_vpn-net --format '{{.Id}}' 2>/dev/null | cut -c1-12)
if [ -n "$SE_BRIDGE" ]; then
    CURRENT=$(ip route show | awk '/^192.168.30.0\/24/ {print $3}')
    if [ "$CURRENT" != "br-$SE_BRIDGE" ]; then
        ip route replace 192.168.30.0/24 dev br-$SE_BRIDGE 2>/dev/null || true
    fi
fi

# Ensure SoftEther OpenVPN mangle rules exist
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
    ip rule show | grep -q "fwmark 0x3 lookup 400" || \
        ip rule add fwmark 0x3 table 400 priority 45
fi

# Ensure SoftEther inbound routing rules exist
if [ -n "$SE_IP" ]; then
    # Ensure default route through windscribe-gw
    SE_DEFAULT=$(docker exec softether ip route show 2>/dev/null | awk '/^default/ {print $3}')
    if [ "$SE_DEFAULT" != "172.21.0.2" ]; then
        docker exec softether ip route replace default via 172.21.0.2 dev eth0 2>/dev/null || true
    fi
    docker exec softether ip route show table 100 2>/dev/null | grep -q default || \
        docker exec softether ip route add default via 172.21.0.1 dev eth0 table 100 2>/dev/null || true
    docker exec softether ip rule show 2>/dev/null | grep -q "fwmark 0x5" || \
        docker exec softether ip rule add fwmark 0x5 table 100 priority 39 2>/dev/null || true
    docker exec softether iptables -t mangle -C OUTPUT \
        -p udp --sport 1194 -j MARK --set-mark 0x5 2>/dev/null || \
        docker exec softether iptables -t mangle -A OUTPUT \
        -p udp --sport 1194 -j MARK --set-mark 0x5 2>/dev/null || true
    docker exec softether iptables -t mangle -C OUTPUT \
        -p tcp --sport 443 -j MARK --set-mark 0x5 2>/dev/null || \
        docker exec softether iptables -t mangle -A OUTPUT \
        -p tcp --sport 443 -j MARK --set-mark 0x5 2>/dev/null || true
fi

# Ensure MTU/MSS settings
WSPID=$(docker inspect windscribe-gw --format '{{.State.Pid}}' 2>/dev/null)
if [ -n "$WSPID" ] && [ "$WSPID" != "0" ]; then
    nsenter -t $WSPID -n ip link set utun420 mtu 1350 2>/dev/null || true
    nsenter -t $WSPID -n iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN \
        -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
    nsenter -t $WSPID -n iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
        -j TCPMSS --clamp-mss-to-pmtu
fi

exit 0
