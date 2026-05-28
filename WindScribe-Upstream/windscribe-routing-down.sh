#!/bin/bash
ip rule del from 10.13.13.0/24 table 400 2>/dev/null || true
ip rule del from 192.168.30.0/24 table 400 2>/dev/null || true
ip rule del fwmark 0x3 table 400 2>/dev/null || true
ip route del default table 400 2>/dev/null || true
ip link del veth-ws-host 2>/dev/null || true
rm -f /var/run/netns/windscribe
