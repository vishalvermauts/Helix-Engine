import os
import sys
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.config import get_config
from lib.logging import get_logger
from agents.triage_router import get_triage_router
from agents.system_monitor import get_system_monitor

logger = get_logger("server", level="INFO", format_type="json")
config = get_config()

pipeline_lock = asyncio.Lock()
execution_state = {
    "status": "idle",
    "last_run": None,
    "pid": None
}

monitor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task
    try:
        logger.info("🚀 Helix Engine initializing...", config=config.to_dict())
        
        if not Path(config.AIDER_BIN).exists():
            logger.warning(f"Aider binary not found at {config.AIDER_BIN}")
        
        workspace_dir = Path(config.WORKSPACE_DIR)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Start system monitor daemon
        monitor = get_system_monitor()
        monitor_task = asyncio.create_task(monitor.run_daemon())
        
        logger.info("✅ Helix Engine startup complete", workspace=str(workspace_dir))
    except Exception as e:
        logger.critical("❌ Startup failed", error=str(e), exc_info=True)
        raise
    
    yield
    
    logger.info("🛑 Helix Engine shutting down...")
    if monitor_task:
        monitor_task.cancel()

app = FastAPI(
    title="Helix Engine Webhook Gateway",
    description="Modern async master control tower",
    lifespan=lifespan
)

# Static mount for /workspace
static_dir = Path(config.WORKSPACE_DIR) / "workspace"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/workspace", StaticFiles(directory=str(static_dir)), name="workspace")

async def send_telegram_message(chat_id: int, text: str, max_retries: int = 2):
    if not config.TELEGRAM_TOKEN:
        return False
        
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    return True
                logger.warning("Telegram send failed", status=response.status_code, attempt=attempt + 1)
        except Exception as e:
            logger.error("Telegram send error", error=str(e), attempt=attempt + 1)
            
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)
            
    logger.error("❌ Telegram message send failed", chat_id=chat_id)
    return False


@app.get("/")
async def root_check():
    return {
        "status": "online",
        "engine": "Helix",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/logs")
async def get_logs():
    log_path = Path("logs/aircode.log")
    if not log_path.exists():
        return JSONResponse(status_code=404, content={"status": "not_found", "message": "Log file not found."})
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return {"logs": lines[-100:]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/status/aider")
async def get_aider_status():
    return execution_state

@app.post("/webhook")
async def telegram_webhook_gateway(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload received.")
    
    message_obj = payload.get("message", {})
    chat_id = message_obj.get("chat", {}).get("id")
    user_id = message_obj.get("from", {}).get("id")
    prompt = message_obj.get("text", "").strip()
    
    if not chat_id or not user_id or not prompt:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "Missing metadata or empty prompt"})
    
    if config.ALLOWED_USER_ID and user_id != config.ALLOWED_USER_ID:
        logger.warning("🔒 Unauthorized access attempt", user_id=user_id, from_chat=chat_id)
        await send_telegram_message(chat_id, "❌ Access Denied.")
        return JSONResponse(status_code=200, content={"status": "denied"})
    
    if prompt.lower() in ["/status", "status"]:
        status_msg = f"✅ Helix Engine Core is online.\nAider Status: {execution_state['status']}"
        if execution_state['last_run']:
            status_msg += f"\nLast run: {execution_state['last_run']}"
        await send_telegram_message(chat_id, status_msg)
        return JSONResponse(status_code=200, content={"status": "status_delivered"})
    
    if prompt.lower() in ["/logs", "logs"]:
        log_path = Path("logs/aircode.log")
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                log_text = "".join(f.readlines()[-15:])
                if len(log_text) > 4000: log_text = log_text[-4000:]
            await send_telegram_message(chat_id, f"📝 Recent Logs:\n```\n{log_text}\n```")
        else:
            await send_telegram_message(chat_id, "⚠️ Log file not found.")
        return JSONResponse(status_code=200, content={"status": "logs_delivered"})
    
    logger.info("📨 Webhook received", user_id=user_id, prompt_len=len(prompt))
    
    selected_model = config.GEMINI_MODEL
    if config.TRIAGE_ENABLED:
        triage_router = get_triage_router()
        triage_result = await triage_router.classify_prompt(prompt)
        selected_model = triage_result.model
        logger.info("📊 Triage complete", classification=triage_result.classification, model=selected_model)
    
    asyncio.create_task(execute_aider_compilation(chat_id, prompt, user_id, selected_model))
    
    return JSONResponse(status_code=200, content={"status": "queued"})


async def execute_aider_compilation(chat_id: int, prompt: str, user_id: int, selected_model: str):
    async with pipeline_lock:
        try:
            logger.info("🔨 Aider execution started", user_id=user_id, model=selected_model)
            await send_telegram_message(chat_id, f"🚀 Executing via Helix Engine...\nModel: {selected_model}")
            
            env = os.environ.copy()
            env["GEMINI_API_KEY"] = config.GEMINI_API_KEY
            env["GEMINI_API_BASE"] = config.GEMINI_API_BASE
            
            workspace_dir = config.WORKSPACE_DIR
            identity_path = f"{workspace_dir}/core_memory/IDENTITY.md"
            profile_path = f"{workspace_dir}/core_memory/PROFILE.md"
            
            aider_cmd = [
                config.AIDER_BIN,
                "--model", selected_model,
                "--no-show-model-warnings",
                "--yes-always",
                "--no-suggest-shell-commands",
                "--no-gitignore",
                "--no-check-update",
                "--read", identity_path,
                "--read", profile_path,
                "--message", prompt
            ]
            
            process = await asyncio.create_subprocess_exec(
                *aider_cmd,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            execution_state["status"] = "running"
            execution_state["pid"] = process.pid
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=config.AIDER_TIMEOUT)
            except asyncio.TimeoutError:
                process.kill()
                logger.error("Aider process timeout")
                await send_telegram_message(chat_id, f"⏱️ Build timeout after {config.AIDER_TIMEOUT}s.")
                return
            
            output_log = stdout.decode().strip()
            error_log = stderr.decode().strip()
            
            if process.returncode == 0:
                success_msg = "✨ Build successfully applied!"
                if output_log:
                    success_msg += f"\n\n```\n{output_log[:500]}\n```"
                await send_telegram_message(chat_id, success_msg)
            else:
                fail_msg = "❌ Build failed."
                if error_log:
                    fail_msg += f"\n\n```\n{error_log[:500]}\n```"
                await send_telegram_message(chat_id, fail_msg)
                
        except Exception as e:
            logger.error("Aider execution error", error=str(e), exc_info=True)
            await send_telegram_message(chat_id, f"⚠️ Build runner failed: {str(e)[:100]}")
        finally:
            execution_state["status"] = "idle"
            execution_state["pid"] = None
            execution_state["last_run"] = datetime.utcnow().isoformat() + "Z"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.PORT, reload=False, log_config=None)
