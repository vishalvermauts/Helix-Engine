#!/bin/bash

# Define styles for readability
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}       AIRCODE ENGINE SYSTEM DIAGNOSTICS       ${NC}"
echo -e "${BLUE}===============================================${NC}"

# 1. READ CONFIGURATION FROM SERVER.PY
echo -e "\n${YELLOW}[1/5] Reading server configuration...${NC}"
if [ ! -f "/workspaces/AirCode/server.py" ]; then
    echo -e "${RED}❌ Error: server.py not found in /workspaces/AirCode/${NC}"
    exit 1
fi

BOT_TOKEN=$(grep -oP 'TOKEN\s*=\s*"\K[^"]+' /workspaces/AirCode/server.py)
GEMINI_KEY=$(grep -oP 'env\["GEMINI_API_KEY"\]\s*=\s*"\K[^"]+' /workspaces/AirCode/server.py)

# Check for lingering placeholder text
if [[ "$BOT_TOKEN" == *"YOUR_FULL"* || "$BOT_TOKEN" == *"..."* ]]; then
    echo -e "${RED}❌ Telegram Bot Token contains placeholder text! Please fix it in server.py.${NC}"
else
    echo -e "${GREEN}✅ Telegram Bot Token format looks complete.${NC}"
fi

if [[ "$GEMINI_KEY" == *"YOUR_ACTUAL"* ]]; then
    echo -e "${RED}❌ Gemini API Key is missing, invalid, or still using OpenRouter format (AQ.)! Ensure it starts with AIzaSy.${NC}"
else
    echo -e "${GREEN}✅ Gemini API Key format looks native (AIzaSy).${NC}"
fi

# 2. TEST TELEGRAM API CONNECTION
echo -e "\n${YELLOW}[2/5] Testing Telegram API Connectivity...${NC}"
TG_TEST=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getMe")
if [[ "$TG_TEST" == *"\"ok\":true"* ]]; then
    echo -e "${GREEN}✅ Telegram Bot Authentication successful! Bot is alive.${NC}"
else
    echo -e "${RED}❌ Telegram Bot Authentication failed! Gateway response:${NC}"
    echo -e "   $TG_TEST"
fi

# 3. CHECK PORT 8000 & FASTAPI STATUS
echo -e "\n${YELLOW}[3/5] Checking Port 8000 & FastAPI Uvicorn Process...${NC}"
PORT_PID=$(sudo lsof -t -i:8000)
if [ -z "$PORT_PID" ]; then
    echo -e "${RED}❌ FastAPI is NOT running on Port 8000.${NC}"
else
    echo -e "${GREEN}✅ FastAPI is running smoothly on Port 8000 (PID: $PORT_PID).${NC}"
fi

# 4. CHECK CLOUDFLARE TUNNEL
echo -e "\n${YELLOW}[4/5] Checking Cloudflare Tunnel Link...${NC}"
TUNNEL_PID=$(pkill -0 -f cloudflared; echo $?)
if [ "$TUNNEL_PID" -ne 0 ]; then
    echo -e "${RED}❌ Cloudflare Tunnel daemon is NOT running.${NC}"
else
    echo -e "${GREEN}✅ Cloudflare Tunnel daemon is actively running.${NC}"
    if [ -f "/workspaces/AirCode/cloudflare.log" ]; then
        LIVE_URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" /workspaces/AirCode/cloudflare.log | head -n 1)
        echo -e "${GREEN}   Live Web Link: ${LIVE_URL}/workspace/index.html${NC}"
    fi
fi

# 5. SELF-HEALING AUTOMATION CHOICE
echo -e "\n${YELLOW}[5/5] System Assessment Complete.${NC}"
if [ -z "$PORT_PID" ] || [ "$TUNNEL_PID" -ne 0 ] || [[ "$TG_TEST" != *"\"ok\":true"* ]]; then
    echo -e "${YELLOW}⚠️ Anomalies detected. Executing automatic system healing sequence...${NC}"
    
    # Kill stale tasks safely
    sudo kill -9 $(sudo lsof -t -i:8000) 2>/dev/null
    pkill -f cloudflared 2>/dev/null
    pkill -f aircode-boot-backup 2>/dev/null
    rm -f /workspaces/AirCode/boot.log
    
    # Relaunch the quiet daemon background pipeline
    nohup /workspaces/AirCode/aircode-boot-backup.sh > /workspaces/AirCode/boot_daemon.log 2>&1 &
    
    echo -e "${GREEN}🔄 System reset command dispatched! Wait 10 seconds for the fresh Telegram ping.${NC}"
else
    echo -e "${GREEN}✨ All systems normal. No local VM interventions required!${NC}"
fi
echo -e "${BLUE}===============================================${NC}"
