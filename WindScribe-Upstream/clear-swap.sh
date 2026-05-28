#!/bin/bash
# Clear swap if usage exceeds 200MB
SWAP_USED=$(free -m | awk '/Swap:/ {print $3}')
if [ "$SWAP_USED" -gt 200 ]; then
    echo "$(date): Swap at ${SWAP_USED}MB - clearing..."
    /sbin/swapoff -a && /sbin/swapon -a
    echo "$(date): Swap cleared"
fi
