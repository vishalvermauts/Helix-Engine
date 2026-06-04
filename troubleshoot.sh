#!/bin/bash

# AirCode VM Troubleshooter
echo "================================================="
echo "        🚀 AirCode Diagnostic Dashboard"
echo "================================================="
echo ""

echo ">>> 1. Active AirCode Processes (server_refactored.py) <<<"
ps aux | grep "[s]erver_refactored.py" | awk '{print "PID: " $2 " | CPU: " $3 "% | MEM: " $4 "% | Started: " $9}'
echo ""

echo ">>> 2. Network Status (Port 8000) <<<"
if command -v netstat &> /dev/null; then
    netstat -tulpn | grep 8000
elif command -v ss &> /dev/null; then
    ss -tulpn | grep 8000
else
    echo "netstat/ss not found. Using lsof..."
    lsof -i :8000
fi
echo ""

echo ">>> 3. Recent Logs (last 20 lines) <<<"
if [ -f "logs/aircode.log" ]; then
    tail -n 20 logs/aircode.log
else
    echo "⚠️ logs/aircode.log not found. The server may not have started or logged anything yet."
fi
echo ""
echo "================================================="
