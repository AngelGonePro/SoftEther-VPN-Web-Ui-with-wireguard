#!/bin/bash
# Apply hairpin NAT inside SoftEther's container network namespace so that
# OpenVPN/L2TP/IKEv2 clients can reach the server's public IP(s) without a
# routing loop. The host-level rules (hairpin service in docker-compose) cover
# the host namespace; these rules cover traffic that exits SoftEther's own
# tun/tap interfaces within its namespace.
if [ -n "$PUBLIC_IPS" ] && [ -n "$LAN_IP" ]; then
  echo "[wrapper] Applying hairpin NAT for: $PUBLIC_IPS -> $LAN_IP"
  IFS=',' read -ra IPS <<< "$PUBLIC_IPS"
  for RAW_IP in "${IPS[@]}"; do
    IP="${RAW_IP%%/*}"   # strip any /32 suffix
    IP="${IP// /}"       # strip spaces
    [ -z "$IP" ] && continue
    CIDR="${IP}/32"
    iptables -t nat -C OUTPUT     -d "$CIDR" -j DNAT --to-destination "$LAN_IP" 2>/dev/null ||       iptables -t nat -A OUTPUT   -d "$CIDR" -j DNAT --to-destination "$LAN_IP"
    iptables -t nat -C POSTROUTING -d "$LAN_IP" -j MASQUERADE 2>/dev/null ||       iptables -t nat -A POSTROUTING -d "$LAN_IP" -j MASQUERADE
    echo "[wrapper] hairpin rule applied: $CIDR -> $LAN_IP"
  done
else
  echo "[wrapper] PUBLIC_IPS or LAN_IP not set — skipping hairpin NAT"
  echo "[wrapper] Set PUBLIC_IPS and LAN_IP in .env to fix VPN routing loop"
fi

# Run original entrypoint
/entrypoint.sh /usr/vpnserver/vpnserver start

# Wait for SoftEther to be ready
sleep 20

echo "[wrapper] Setting admin password..."
# Only try with current SPW — blank password attempt hangs when password already set
timeout -k 3 8 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD ServerPasswordSet "$SPW" 2>/dev/null || true

echo "[wrapper] Enabling OpenVPN..."
timeout -k 3 8 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD OpenVpnEnable yes /PORTS:1194 2>/dev/null || true

echo "[wrapper] Enabling L2TP/IPsec..."
timeout -k 3 8 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD IPsecEnable /L2TP:yes /L2TPRAW:yes /ETHERIP:no /PSK:"$PSK" /DEFAULTHUB:DEFAULT 2>/dev/null || true

echo "[wrapper] Enabling SSTP..."
timeout -k 3 8 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD SstpEnable yes 2>/dev/null || true

echo "[wrapper] Done"
exec tail -f /dev/null
