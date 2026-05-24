#!/bin/bash
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
