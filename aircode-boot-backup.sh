#!/bin/bash
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Helix Engine Custom Quiet Boot ==="

# 1. Kill any existing loose processes to clear the board
sudo kill -9 $(sudo lsof -t -i:8000) 2>/dev/null
pkill -f cloudflared 2>/dev/null
pkill -f server.py 2>/dev/null

# 2. Start the FastAPI Server in the background
cd /workspaces/AirCode
python3 server.py > boot.log 2>&1 &

# Give Uvicorn 3 seconds to claim port 8000
sleep 3

# 3. Start Cloudflare Tunnel and log its output
rm -f cloudflare.log
nohup cloudflared tunnel --url http://localhost:8000 > cloudflare.log 2>&1 &

# Give the tunnel 8 seconds to cleanly handshake with the edge network
sleep 15

# 4. Extract the unique URL EXACTLY ONCE
TUNNEL_URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" cloudflare.log | head -n 1)

if [ ! -z "$TUNNEL_URL" ]; then
    TOKEN="8982235895:AA..." # Your bot token is preserved here
    CHAT_ID="7569308974"     # Your chat ID
    MESSAGE="🚀 Helix Engine Tunnel Sync Active! %0A%0A🌐 $TUNNEL_URL"
    
    # Send ONE single notification to Telegram
    curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" -d "chat_id=$CHAT_ID&text=$MESSAGE" > /dev/null
    echo "Startup notification sent. Muting background loop."
else
    echo "Error: Tunnel URL could not be parsed on startup."
fi
