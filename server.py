import os
import sys
import asyncio
import subprocess
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import httpx

# 1. LOAD SYSTEM ENVIRONMENT CONFIGURATION
ENV_PATH = "/workspaces/AirCode/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()  # Fallback to current working directory

# 2. EXTRACT VALIDATED SYSTEM VARIABLES
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")

if not TELEGRAM_TOKEN or not ALLOWED_USER_ID:
    print("❌ ERROR: TELEGRAM_TOKEN or ALLOWED_USER_ID is missing from .env file!")
    sys.exit(1)

try:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)
except ValueError:
    print("❌ ERROR: ALLOWED_USER_ID in .env must be a valid numeric ID!")
    sys.exit(1)

# 3. INITIALIZE FASTAPI INTERFACE
app = FastAPI(title="AirCode Engine Webhook Gateway")

# Global concurrency lock to prevent simultaneous Git/Aider write operations
pipeline_lock = asyncio.Lock()

async def send_telegram_message(chat_id: int, text: str):
    """Helper function to route live execution notifications back to your device."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        print(f"⚠️ Failed to dispatch Telegram log update: {e}")

@app.get("/")
async def root_check():
    return {"status": "online", "engine": "AirCode", "gateway": "FastAPI"}

@app.post("/webhook")
async def telegram_webhook_gateway(request: Request):
    """
    Core webhook interceptor. Captures Telegram payloads, evaluates access permissions,
    and dispatches tasks directly into the automated Aider execution loop.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload received.")

    # Extract messaging context
    if "message" not in payload:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "No message object present"})

    message_obj = payload["message"]
    chat_id = message_obj.get("chat", {}).get("id")
    user_id = message_obj.get("from", {}).get("id")
    prompt = message_obj.get("text", "").strip()

    if not chat_id or not user_id:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "Missing metadata indices"})

    # 🛑 FIREWALL CHECK: Instant lockout if the user ID doesn't match your whitelisted profile
    if user_id != ALLOWED_USER_ID:
        print(f"🔒 Security Alert: Unauthorized webhook interaction rejected from User ID {user_id}")
        await send_telegram_message(chat_id, "❌ Access Denied: Unauthorized terminal operator footprint detected.")
        return JSONResponse(status_code=200, content={"status": "denied"})

    if not prompt:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "Empty string prompt content"})

    # Handle built-in diagnostic text requests safely
    if prompt.lower() in ["/status", "status"]:
        await send_telegram_message(chat_id, "✅ AirCode Engine Core is online, authenticated, and ready to compile!")
        return JSONResponse(status_code=200, content={"status": "status_delivered"})

    # Trigger Aider code generation context asynchronously to prevent webhook time-outs
    asyncio.create_task(execute_aider_compilation(chat_id, prompt))
    
    return JSONResponse(status_code=200, content={"status": "queued", "task": "Aider processing loop initiated"})

async def execute_aider_compilation(chat_id: int, prompt: str):
    """
    Asynchronous runner that prepares system environments, resolves Google AI routing targets,
    and runs the Aider code modifier against your workspace repository files.
    """
    async with pipeline_lock:
        # Build child execution shell variables
        env = os.environ.copy()

        # Gather real-time keys from the systemic .env map
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        
        # Inject keys straight into the working process memory
        env["GEMINI_API_KEY"] = gemini_key
        
        # 🎯 CRITICAL BUG FIX: Force LiteLLM to route the 'AQ.Ab' key format to the 
        # direct AI Studio endpoint instead of defaulting to Enterprise Vertex AI paths
        env["GEMINI_API_BASE"] = "https://generativelanguage.googleapis.com/v1beta"
        env["LITELLM_MODE"] = "production"

        # Define and build deployment workspaces
        workspace_dir = "/workspaces/AirCode"
        os.makedirs(workspace_dir, exist_ok=True)

        await send_telegram_message(chat_id, "🚀 [AirCode] API Credentials Verified. Spawning Aider build agent...")

        # Construct safe non-interactive arguments for the Aider runner
        aider_cmd = [
            "/home/vboxuser/.local/bin/aider",
            "--model", "gemini/gemini-2.5-pro",
            "--no-show-model-warnings",
            "--yes-always",
            "--no-suggest-shell-commands",
            "--no-gitignore",
            "--no-check-update",
            "--message", prompt
        ]

        try:
            # Spawn process securely inside the specific project workspace folder
            process = await asyncio.create_subprocess_exec(
                *aider_cmd,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await process.communicate()
            
            output_log = stdout.decode().strip()
            error_log = stderr.decode().strip()

            if process.returncode == 0:
                success_msg = "✨ [AirCode] Build successfully applied & committed to the repository!"
                if output_log:
                    success_msg = success_msg + "\n\n" + output_log
                await send_telegram_message(chat_id, success_msg)
            else:
                fail_msg = "❌ [AirCode] Build failed."
                if error_log:
                    fail_msg = fail_msg + "\n\n" + error_log
                await send_telegram_message(chat_id, fail_msg)
        except Exception as e:
            await send_telegram_message(chat_id, f"⚠️ [AirCode] Runner failed: {e}")