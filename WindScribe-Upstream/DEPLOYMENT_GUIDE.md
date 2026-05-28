# VPN Stack Deployment Guide
## Full deployment from scratch on a new Debian 12 VPS

---

## File Structure

```
~/windscribe-gw/
├── docker-compose.yml
├── Dockerfile
└── entrypoint.sh

~/softether-vpn/
├── .env                          ← copy from env.example, fill in values
├── docker-compose.yml
├── hairpin.sh
├── vpn_server.config             ← your existing SoftEther config
├── softether/
│   ├── Dockerfile
│   └── entrypoint-wrapper.sh
├── wg-api/
│   ├── Dockerfile
│   └── app.py
├── wg-data/                      ← create empty, wg-api fills it
└── ui/
    ├── index.html
    └── nginx.conf

/usr/local/bin/
├── windscribe-routing.sh
├── windscribe-routing-down.sh
├── windscribe-watchdog.sh
└── clear-swap.sh

/etc/systemd/system/
├── windscribe-gw.service
├── softether-vpn.service
├── windscribe-routing.service
├── windscribe-watchdog.service
└── windscribe-watchdog.timer
```

---

## Step 1 — System Prerequisites

```bash
apt update && apt upgrade -y
apt install -y iproute2 iptables conntrack curl

# Install Docker
curl -fsSL https://get.docker.com | sh

# Enable IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
echo "net.ipv4.conf.all.src_valid_mark=1" >> /etc/sysctl.conf
echo "net.netfilter.nf_conntrack_max=65536" >> /etc/sysctl.conf
echo "vm.swappiness=10" >> /etc/sysctl.conf
echo "net.ipv4.tcp_window_scaling=1" >> /etc/sysctl.conf
echo "net.ipv4.tcp_sack=1" >> /etc/sysctl.conf
echo "net.core.rmem_max=16777216" >> /etc/sysctl.conf
echo "net.core.wmem_max=16777216" >> /etc/sysctl.conf
sysctl -p

# Create wsuser (Windscribe MUST run as non-root)
useradd -m -s /bin/bash wsuser
loginctl enable-linger wsuser
```

---

## Step 2 — Install Windscribe CLI on Host

```bash
curl -fsSL https://deploy.totallyacdn.com/desktop-apps/2.22.10/windscribe-cli_2.22.10_amd64.deb \
    -o /tmp/windscribe-cli.deb
apt-get install -y /tmp/windscribe-cli.deb
rm /tmp/windscribe-cli.deb
```

---

## Step 3 — Login to Windscribe (CRITICAL — read carefully)

Windscribe CANNOT be logged in as root or via plain `su`.
It MUST use a real systemd user session via machinectl:

```bash
machinectl shell wsuser@ /bin/bash
```

Inside the wsuser shell:
```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
/opt/windscribe/Windscribe &
sleep 5
windscribe-cli login
# Enter username and password (and 2FA if enabled)
sleep 3
windscribe-cli connect Ranch wireguard
sleep 10
windscribe-cli status
# Should show: Connected: Dallas - Ranch, Protocol: WireGuard:443
windscribe-cli disconnect
exit
```

### Migrating session from existing server
```bash
# On old server:
tar czf windscribe-session.tar.gz \
    /home/wsuser/.config/Windscribe \
    /home/wsuser/.local/share/Windscribe

# On new server:
tar xzf windscribe-session.tar.gz -C /
chown -R wsuser:wsuser /home/wsuser/.config/Windscribe
chown -R wsuser:wsuser /home/wsuser/.local/share/Windscribe
# Then verify with machinectl shell above
```

---

## Step 4 — Deploy Files

```bash
# Create directories
mkdir -p ~/windscribe-gw
mkdir -p ~/softether-vpn/softether
mkdir -p ~/softether-vpn/wg-api
mkdir -p ~/softether-vpn/wg-data
mkdir -p ~/softether-vpn/ui

# Copy windscribe-gw files
cp windscribe-gw-docker-compose.yml ~/windscribe-gw/docker-compose.yml
cp windscribe-gw-Dockerfile ~/windscribe-gw/Dockerfile
cp entrypoint.sh ~/windscribe-gw/entrypoint.sh
chmod +x ~/windscribe-gw/entrypoint.sh

# Copy softether-vpn files
cp softether-docker-compose.yml ~/softether-vpn/docker-compose.yml
cp .env ~/softether-vpn/.env
cp vpn_server.config ~/softether-vpn/vpn_server.config
cp hairpin.sh ~/softether-vpn/hairpin.sh
cp softether-Dockerfile ~/softether-vpn/softether/Dockerfile
cp entrypoint-wrapper.sh ~/softether-vpn/softether/entrypoint-wrapper.sh
cp wg-api-Dockerfile ~/softether-vpn/wg-api/Dockerfile
cp app.py ~/softether-vpn/wg-api/app.py
cp index.html ~/softether-vpn/ui/index.html
cp nginx.conf ~/softether-vpn/ui/nginx.conf

# Copy system scripts
cp windscribe-routing.sh /usr/local/bin/windscribe-routing.sh
cp windscribe-routing-down.sh /usr/local/bin/windscribe-routing-down.sh
cp windscribe-watchdog.sh /usr/local/bin/windscribe-watchdog.sh
cp clear-swap.sh /usr/local/bin/clear-swap.sh
chmod +x /usr/local/bin/windscribe-routing.sh
chmod +x /usr/local/bin/windscribe-routing-down.sh
chmod +x /usr/local/bin/windscribe-watchdog.sh
chmod +x /usr/local/bin/clear-swap.sh

# Copy systemd services
cp windscribe-gw.service /etc/systemd/system/
cp softether-vpn.service /etc/systemd/system/
cp windscribe-routing.service /etc/systemd/system/
cp windscribe-watchdog.service /etc/systemd/system/
cp windscribe-watchdog.timer /etc/systemd/system/
```

---

## Step 5 — Setup Swap Auto-Clear Cron

```bash
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/clear-swap.sh >> /var/log/clear-swap.log 2>&1") | crontab -
```

---

## Step 6 — Enable and Start Services

```bash
systemctl daemon-reload
systemctl enable windscribe-gw.service
systemctl enable softether-vpn.service
systemctl enable windscribe-routing.service
systemctl enable windscribe-watchdog.timer

# Start in correct order
systemctl start windscribe-gw.service
sleep 65
systemctl start softether-vpn.service
sleep 20
systemctl start windscribe-routing.service
systemctl start windscribe-watchdog.timer
```

---

## Step 7 — Verify

```bash
# All services running?
systemctl status windscribe-gw.service softether-vpn.service \
    windscribe-routing.service windscribe-watchdog.timer

# All containers running?
docker ps

# Windscribe connected and showing Ranch IP (NOT your VPS IP)?
docker exec windscribe-gw curl -s ifconfig.me

# SoftEther routing correctly?
docker exec softether ip route show
# Should show: default via 172.21.0.2

# SoftEther inbound rules?
docker exec softether ip rule show
# Should show fwmark 0x4 and 0x5

# Host routing rules?
ip rule show | grep "400\|0x3"
iptables -t mangle -L PREROUTING -n | grep "172.21"
```

---

## Boot Order (automatic after setup)

1. `windscribe-gw.service` → starts container, waits 60s for Windscribe to connect to Ranch
2. `softether-vpn.service` → waits for windscribe_net, starts VPN stack
3. `windscribe-routing.service` → waits 30s, sets up all veth/routing/mangle/iptables rules
4. `windscribe-watchdog.timer` → fires 120s after boot, then every 60s to monitor and recover

---

## What the Watchdog Monitors

- windscribe-gw container running
- utun420 tunnel up
- Internet reachable through Windscribe tunnel
- veth-ws-host exists
- SoftEther 192.168.30.0/24 route uses correct bridge
- SoftEther mangle/conntrack rules exist
- SoftEther inbound routing rules exist
- MTU/MSS settings correct

---

## VPN Performance Summary

| Protocol | Speed | Use Case |
|---|---|---|
| WireGuard UDP 51820 | Fastest | Daily use, streaming, 4K |
| OpenVPN UDP 9194 | Fast | Good compatibility |
| OpenVPN TCP 8443 | Slower | Hotel/censored networks only |

---

## Windscribe Troubleshooting

**"Internet connectivity not available"**
```bash
GW_IFACE=$(docker exec windscribe-gw ip -o addr show | awk '/10\.200\.0\./ {print $2}')
docker exec windscribe-gw ip route add default via 10.200.0.1 dev $GW_IFACE 2>/dev/null || true
docker exec windscribe-gw su - wsuser -c \
    'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus && windscribe-cli connect Ranch wireguard'
```

**VPN not showing Windscribe IP**
```bash
systemctl restart windscribe-routing.service
```

**OpenVPN inbound not connecting**
```bash
# Check SoftEther routing rules
docker exec softether ip rule show
docker exec softether ip route show table 100
docker exec softether iptables -t mangle -L OUTPUT -n
# If missing, restart routing:
systemctl restart windscribe-routing.service
```

**Swap filling up causing slowness**
```bash
/sbin/swapoff -a && /sbin/swapon -a
# Auto-clears every 5min via cron if >200MB
```

**Windscribe session expired**
```bash
loginctl enable-linger wsuser
machinectl shell wsuser@ /bin/bash -c \
    'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus && windscribe-cli connect Ranch wireguard'
```
