#!/bin/bash
# Helix Engine Diagnostics Utility
# Runs 100% unattended

echo "========================================"
echo "    🧬 Helix Engine Diagnostics"
echo "========================================"
echo ""

echo ">>> 1. Environment Verification <<<"
if [ -f ".env" ]; then
    echo "✅ .env file found."
    # Extract token directly to avoid printing it
    TELEGRAM_TOKEN=$(grep '^TELEGRAM_TOKEN=' .env | cut -d '=' -f2 | tr -d '"' | tr -d "'")
    if [ -n "$TELEGRAM_TOKEN" ]; then
        echo "✅ TELEGRAM_TOKEN found in .env."
    else
        echo "❌ TELEGRAM_TOKEN missing from .env."
    fi
else
    echo "❌ .env file missing!"
fi
echo ""

echo ">>> 2. Telegram API Handshake <<<"
if [ -n "$TELEGRAM_TOKEN" ]; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.telegram.org/bot${TELEGRAM_TOKEN}/getMe)
    if [ "$HTTP_STATUS" == "200" ]; then
        echo "✅ Telegram Authentication Successful (200 OK)."
    else
        echo "❌ Telegram Authentication Failed (HTTP $HTTP_STATUS). Check your token."
    fi
else
    echo "⚠️ Skipping Telegram handshake (No token)."
fi
echo ""

echo ">>> 3. Server Port Verification (Port 8000) <<<"
if command -v ss &> /dev/null; then
    if ss -tulpn | grep -q ":8000"; then
        echo "✅ Port 8000 is occupied (FastAPI is running)."
    else
        echo "❌ Port 8000 is free (FastAPI is NOT running)."
    fi
elif command -v netstat &> /dev/null; then
    if netstat -tulpn | grep -q ":8000"; then
        echo "✅ Port 8000 is occupied (FastAPI is running)."
    else
        echo "❌ Port 8000 is free (FastAPI is NOT running)."
    fi
else
    echo "⚠️ ss and netstat not found. Skipping port check."
fi
echo ""

echo ">>> 4. Active Cloudflare Tunnel <<<"
if [ -f "cloudflare.log" ]; then
    TUNNEL_URL=$(grep -oE "https://[a-zA-Z0-9-]+\.trycloudflare\.com" cloudflare.log | tail -n 1)
    if [ -n "$TUNNEL_URL" ]; then
        echo "✅ Active Tunnel: $TUNNEL_URL"
    else
        echo "⚠️ No active trycloudflare.com URL found in logs."
    fi
else
    echo "⚠️ cloudflare.log not found."
fi
echo ""
echo "========================================"
