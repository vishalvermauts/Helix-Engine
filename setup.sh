#!/bin/bash

echo "🚀 Welcome to the Helix Engine Setup Wizard!"
echo "============================================="

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed. Please install it and try again."
    exit 1
fi

# 2. Prompt for API Keys
echo ""
echo "🔑 Let's configure your API keys."
read -p "Enter your Gemini API Key: " GEMINI_KEY
read -p "Enter your DeepSeek API Key (Optional, press enter to skip): " DEEPSEEK_KEY
read -p "Enter your Telegram Bot Token: " TELEGRAM_TOKEN
read -p "Enter your Telegram Chat ID: " TELEGRAM_CHAT_ID

# 3. Generate .env file
echo ""
echo "📝 Generating .env file..."
cat <<EOF > .env
# TELEGRAM INTEGRATION
TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
ALLOWED_USER_ID=${TELEGRAM_CHAT_ID}

# LLM PROVIDERS
GEMINI_API_KEY=${GEMINI_KEY}
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}

# LLM ROUTING
GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1beta
GEMINI_MODEL=gemini/gemini-2.5-pro
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# LOCAL DEPLOYMENT
WORKSPACE_DIR=./workspace
AIDER_BIN=aider

# TIMEOUTS & LIMITS
AIDER_TIMEOUT=300
TELEGRAM_TIMEOUT=10
HEALTH_CHECK_INTERVAL=60

# LOGGING
LOG_LEVEL=INFO
LOG_FORMAT=json

# ADVANCED TUNING
GIT_AUTO_COMMIT=true
MAX_CONCURRENT_TASKS=1
RETRY_ATTEMPTS=3
RETRY_BACKOFF_BASE=2.0

# TRIAGE ROUTER
TRIAGE_ENABLED=true
TRIAGE_TIMEOUT=0.3
TRIAGE_FALLBACK_MODEL=gemini/gemini-2.5-pro
EOF
echo "✅ .env file created successfully!"

# 4. Setup Python Environment
echo ""
echo "🐍 Creating virtual environment and installing dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Start the Engine
echo ""
echo "🌟 Setup Complete! Booting up the Helix Engine with Auto-Tunneling..."
echo "===================================================================="
uvicorn server:app --host 0.0.0.0 --port 8000
