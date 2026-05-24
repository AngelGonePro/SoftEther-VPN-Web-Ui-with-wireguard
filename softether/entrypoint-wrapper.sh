#!/bin/bash
# Run original entrypoint which sets up users/hub then starts SoftEther
# The original entrypoint starts vpnserver as a daemon and exits
/entrypoint.sh /usr/vpnserver/vpnserver start

# Wait for SoftEther to be ready
sleep 20

# Set admin password
echo "[wrapper] Setting admin password..."
vpncmd localhost:5555 /SERVER /PASSWORD: /CMD ServerPasswordSet "$SPW" 2>/dev/null || true
vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD ServerPasswordSet "$SPW" 2>/dev/null || true

# Enable OpenVPN
echo "[wrapper] Enabling OpenVPN..."
vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD OpenVpnEnable yes /PORTS:1194 2>/dev/null || true

# Enable L2TP/IPsec
echo "[wrapper] Enabling L2TP/IPsec..."
vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD IPsecEnable /L2TP:yes /L2TPRAW:yes /ETHERIP:no /PSK:"$PSK" /DEFAULTHUB:DEFAULT 2>/dev/null || true

# Enable SSTP
echo "[wrapper] Enabling SSTP..."
vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD SstpEnable yes 2>/dev/null || true

echo "[wrapper] All protocols enabled — keeping container alive"

# Keep container alive by monitoring vpnserver process
while true; do
    if ! pgrep -x vpnserver > /dev/null 2>&1; then
        echo "[wrapper] SoftEther process not found, restarting..."
        /usr/vpnserver/vpnserver start
        sleep 5
    fi
    sleep 10
done
