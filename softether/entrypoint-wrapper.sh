#!/bin/bash
# Wrapper that ensures admin password is always set from SPW env var
# on every startup — not just first run. This means reboots and
# restarts never break the password.

# Start SoftEther in background using original entrypoint
/entrypoint.sh /usr/vpnserver/vpnserver start &
BGPID=$!

# Wait for SoftEther to be ready
sleep 20

# Always set the admin password from SPW env var
echo "[wrapper] Setting admin password..."
echo "$SPW" | vpncmd localhost:5555 /SERVER /PASSWORD: /CMD ServerPasswordSet "$SPW" 2>/dev/null || true
echo "$SPW" | vpncmd localhost:5555 /SERVER /PASSWORD:"$SPW" /CMD ServerPasswordSet "$SPW" 2>/dev/null || true
echo "[wrapper] Done"

# Keep container alive
wait $BGPID
