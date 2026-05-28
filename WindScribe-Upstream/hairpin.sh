#!/bin/sh
set -e
apk add --no-cache iptables iproute2 > /dev/null 2>&1

MISSING=""
[ -z "$PUBLIC_IPS" ] && MISSING="PUBLIC_IPS $MISSING"
[ -z "$LAN_IP"     ] && MISSING="LAN_IP $MISSING"
[ -z "$WG_SUBNET"  ] && MISSING="WG_SUBNET $MISSING"
if [ -n "$MISSING" ]; then
  echo "[hairpin] ERROR: missing required env vars: $MISSING"
  exit 1
fi

echo "[hairpin] PUBLIC_IPS = $PUBLIC_IPS"
echo "[hairpin] LAN_IP     = $LAN_IP"
echo "[hairpin] WG_SUBNET  = $WG_SUBNET"
echo "[hairpin] SE_SUBNET  = ${SE_SUBNET:-not set}"

# WireGuard uses host network so route via wg0 directly
if ip link show wg0 &>/dev/null; then
  ip route show | grep -q "^$WG_SUBNET " && \
    ip route del $WG_SUBNET 2>/dev/null || true
  ip route add "$WG_SUBNET" dev wg0 2>/dev/null || true
  echo "[hairpin] added WireGuard route: $WG_SUBNET dev wg0"
else
  echo "[hairpin] WARNING: wg0 not found yet"
fi

# SoftEther/OpenVPN subnet via vpn-net bridge (172.21.0.x)
if [ -n "$SE_SUBNET" ]; then
  SE_BRIDGE=$(ip -o -4 addr show | awk '/172\.21\.0\.1/{print $2}')
  if [ -n "$SE_BRIDGE" ]; then
    ip route show | grep -q "^$SE_SUBNET " && \
      ip route del $SE_SUBNET 2>/dev/null || true
    ip route add "$SE_SUBNET" dev "$SE_BRIDGE" 2>/dev/null || true
    echo "[hairpin] added OpenVPN route: $SE_SUBNET dev $SE_BRIDGE"
  fi
fi

# Hairpin NAT rules
IFS=','
for RAW in $PUBLIC_IPS; do
  IP=$(echo "$RAW" | tr -d ' ' | sed 's|/32||g')
  [ -z "$IP" ] && continue
  CIDR="${IP}/32"
  iptables -t nat -C OUTPUT -d "$CIDR" -j DNAT --to-destination "$LAN_IP" 2>/dev/null \
    || iptables -t nat -A OUTPUT -d "$CIDR" -j DNAT --to-destination "$LAN_IP"
  iptables -t nat -C POSTROUTING -d "$LAN_IP" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -d "$LAN_IP" -j MASQUERADE
  iptables -t nat -C POSTROUTING -s "$LAN_IP" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$LAN_IP" -j MASQUERADE
  echo "[hairpin] NAT applied: $CIDR -> $LAN_IP"
done

echo "[hairpin] ── NAT OUTPUT rules ──"
iptables -t nat -L OUTPUT -n | grep DNAT || true
echo "[hairpin] all done"
