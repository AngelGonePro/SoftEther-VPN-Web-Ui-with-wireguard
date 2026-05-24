#!/bin/bash
# Run original entrypoint (sets up users/hub/starts SoftEther daemon)
/entrypoint.sh /usr/vpnserver/vpnserver start

# Wait for SoftEther to be ready
sleep 20

# Set admin password with timeout
echo "[wrapper] Setting admin password..."
timeout 10 vpncmd localhost:5555 /SERVER /PASSWORD: /CMD ServerPasswordSet "$SPW" 2>/dev/null || true
timeout 10 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD ServerPasswordSet "$SPW" 2>/dev/null || true

# Enable protocols with timeouts
echo "[wrapper] Enabling OpenVPN..."
timeout 10 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD OpenVpnEnable yes /PORTS:1194 2>/dev/null || true

echo "[wrapper] Enabling L2TP/IPsec..."
timeout 10 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD IPsecEnable /L2TP:yes /L2TPRAW:yes /ETHERIP:no /PSK:"$PSK" /DEFAULTHUB:DEFAULT 2>/dev/null || true

echo "[wrapper] Enabling SSTP..."
timeout 10 vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD SstpEnable yes 2>/dev/null || true

echo "[wrapper] Done"
exec tail -f /dev/null
