#!/bin/bash
# AirCode Boot Agent - Secure Startup Pipeline
# Spawns: FastAPI server, Cloudflare tunnel, system monitor agent

set -e

cd /workspaces/AirCode

# Load environment from .env
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ Error: .env file not found"
    exit 1
fi

LOG_DIR="/workspaces/AirCode/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === AirCode Secure Boot Sequence ==="

# 1. Kill existing loose processes
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up stale processes..."
sudo kill -9 $(sudo lsof -t -i:8000 2>/dev/null) 2>/dev/null || true
pkill -f cloudflared 2>/dev/null || true
pkill -f "python3.*server.py" 2>/dev/null || true
pkill -f "python3.*system_monitor" 2>/dev/null || true

sleep 1

# 2. Start FastAPI Server (using improved server.refactored.py if available)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting FastAPI server..."
if [ -f "server.refactored.py" ]; then
    python3 server.refactored.py > "$LOG_DIR/server_$TIMESTAMP.log" 2>&1 &
else
    python3 server.py > "$LOG_DIR/server_$TIMESTAMP.log" 2>&1 &
fi

SERVER_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] FastAPI started (PID: $SERVER_PID)"
sleep 3

# 3. Start Cloudflare Tunnel
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Cloudflare tunnel..."
rm -f cloudflare.log
nohup cloudflared tunnel --url http://localhost:8000 > cloudflare.log 2>&1 &
TUNNEL_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cloudflare tunnel started (PID: $TUNNEL_PID)"

# Wait for tunnel to initialize
sleep 15

# 4. Extract tunnel URL and start system monitor
TUNNEL_URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" cloudflare.log | head -n 1)

if [ ! -z "$TUNNEL_URL" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Tunnel URL: $TUNNEL_URL"
    
    # Send startup notification (using env var, not hardcoded)
    MESSAGE="🚀 AirCode Tunnel Sync Active!%0A%0A🌐 $TUNNEL_URL"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}&text=${MESSAGE}" > /dev/null || true
    
    # 5. Start system monitor agent
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting system monitor agent..."
    python3 agents/system_monitor.py > "$LOG_DIR/monitor_$TIMESTAMP.log" 2>&1 &
    MONITOR_PID=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] System monitor started (PID: $MONITOR_PID)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  Warning: Tunnel URL could not be parsed. Skipping webhook sync."
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Boot sequence complete ==="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server PID: $SERVER_PID | Tunnel PID: $TUNNEL_PID | Monitor PID: ${MONITOR_PID:-N/A}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Logs: $LOG_DIR/"

# Keep script alive to prevent background processes from orphaning
wait
