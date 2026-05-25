#!/bin/sh
# Host-level network fix script.
# Runs with network_mode: host so all changes apply to the HOST namespace.
#
# Fixes TWO problems:
#
# 1. MISSING ROUTES: nginx runs on the host (network_mode: host) but the
#    WireGuard tunnel routes (10.13.13.0/24) and OpenVPN routes only exist
#    inside their respective container namespaces. The host kernel has no
#    idea how to reach VPN client IPs, so response packets go out eth0 and
#    vanish. Fix: add routes pointing VPN subnets at the correct container.
#
# 2. HAIRPIN NAT: VPN clients trying to reach the server's own public IP
#    hit a routing loop. Fix: DNAT the public IP to the LAN IP in the host
#    OUTPUT chain so the kernel routes responses correctly.

set -e
apk add --no-cache iptables iproute2 > /dev/null 2>&1

# ── Validate required env vars ────────────────────────────────────────────────
MISSING=""
[ -z "$PUBLIC_IPS" ] && MISSING="PUBLIC_IPS $MISSING"
[ -z "$LAN_IP"     ] && MISSING="LAN_IP $MISSING"
[ -z "$WG_SUBNET"  ] && MISSING="WG_SUBNET $MISSING"
if [ -n "$MISSING" ]; then
  echo "[hairpin] ERROR: missing required env vars: $MISSING"
  echo "[hairpin] Set them in .env and restart"
  exit 1
fi

echo "[hairpin] PUBLIC_IPS = $PUBLIC_IPS"
echo "[hairpin] LAN_IP     = $LAN_IP"
echo "[hairpin] WG_SUBNET  = $WG_SUBNET"
echo "[hairpin] SE_SUBNET  = ${SE_SUBNET:-not set, skipping}"

# ── 1. VPN subnet routes on the host ─────────────────────────────────────────
# WireGuard: route 10.13.13.0/24 (or whatever WG_SUBNET is) via the wireguard
# container's gateway on the vpn-net bridge. We find the bridge gateway by
# inspecting the wireguard container's network.
echo "[hairpin] looking up wireguard container gateway..."
WG_GW=""
# Try common bridge subnets — the gateway is always .1 of the bridge subnet
for iface in $(ip -o -4 addr show | awk '{print $2}' | grep -E '^br-'); do
  BRIDGE_IP=$(ip -o -4 addr show "$iface" 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
  if [ -n "$BRIDGE_IP" ]; then
    WG_GW="$BRIDGE_IP"
    echo "[hairpin] found bridge $iface gateway: $WG_GW"
    break
  fi
done

if [ -n "$WG_GW" ]; then
  # Add WireGuard subnet route via the vpn-net bridge gateway
  if ip route show | grep -q "^$WG_SUBNET "; then
    echo "[hairpin] WireGuard route already exists: $(ip route show $WG_SUBNET)"
  else
    ip route add "$WG_SUBNET" via "$WG_GW"
    echo "[hairpin] added route: $WG_SUBNET via $WG_GW"
  fi

  # Add SoftEther/OpenVPN subnet route if configured
  if [ -n "$SE_SUBNET" ]; then
    if ip route show | grep -q "^$SE_SUBNET "; then
      echo "[hairpin] OpenVPN route already exists: $(ip route show $SE_SUBNET)"
    else
      ip route add "$SE_SUBNET" via "$WG_GW"
      echo "[hairpin] added route: $SE_SUBNET via $WG_GW"
    fi
  fi
else
  echo "[hairpin] WARNING: could not find bridge gateway — VPN response routing may fail"
  echo "[hairpin] Current interfaces:"
  ip -o -4 addr show | awk '{print $2, $4}'
fi

# ── 2. Hairpin NAT rules ──────────────────────────────────────────────────────
IFS=','
for RAW in $PUBLIC_IPS; do
  IP=$(echo "$RAW" | tr -d ' ' | sed 's|/32||g')
  [ -z "$IP" ] && continue
  CIDR="${IP}/32"
  echo "[hairpin] applying NAT: $CIDR -> $LAN_IP"

  iptables -t nat -C OUTPUT -d "$CIDR" -j DNAT --to-destination "$LAN_IP" 2>/dev/null \
    || iptables -t nat -A OUTPUT -d "$CIDR" -j DNAT --to-destination "$LAN_IP"

  iptables -t nat -C POSTROUTING -d "$LAN_IP" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -d "$LAN_IP" -j MASQUERADE

  # Critical: MASQUERADE responses FROM LAN_IP so they appear to come from
  # the public IP, not 192.168.x.x. This is what wg-easy had that made it
  # work — without it the client drops the response (wrong source IP).
  iptables -t nat -C POSTROUTING -s "$LAN_IP" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$LAN_IP" -j MASQUERADE

  echo "[hairpin] done: $CIDR"
done

echo ""
echo "[hairpin] ── Final routing table (VPN subnets) ──"
ip route show | grep -E "10\.|172\.|192\." || true
echo ""
echo "[hairpin] ── NAT OUTPUT rules ──"
iptables -t nat -L OUTPUT -n | grep DNAT || true
echo ""
echo "[hairpin] all done"
