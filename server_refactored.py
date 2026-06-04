"""
Helix Engine Webhook Gateway - Refactored with Lifespan & Structured Logging
Handles Telegram webhook events and dispatches Aider code compilation tasks.
"""

import os
import sys
import asyncio
import subprocess
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.config import get_config, reload_config
from lib.logging import get_logger
from agents.triage_router import get_triage_router

# Initialize logger & config
logger = get_logger("server", level="INFO", format_type="json")
config = get_config()

# Global concurrency lock to prevent simultaneous Git/Aider write operations
pipeline_lock = asyncio.Lock()
execution_state = {
    "status": "idle",
    "last_run": None,
    "pid": None
}


# ============================================================================
# LIFESPAN CONTEXT MANAGER (FastAPI 0.93+)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup & shutdown hooks.
    Validates config on startup, logs lifecycle events.
    """
    # === STARTUP ===
    try:
        logger.info("🚀 Helix Engine initializing...", config=config.to_dict())
        
        # Validate critical paths exist
        if not Path(config.aider_bin).exists():
            raise FileNotFoundError(f"Aider binary not found: {config.aider_bin}")
        
        if not Path(config.workspace_dir).exists():
            Path(config.workspace_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info("✅ Helix Engine startup complete", workspace=config.workspace_dir)
    
    except Exception as e:
        logger.critical("❌ Startup failed", error=str(e), exc_info=True)
        raise
    
    yield  # App runs here
    
    # === SHUTDOWN ===
    logger.info("🛑 Helix Engine shutting down...")
    # Add cleanup here if needed (kill spawned processes, etc.)


# ============================================================================
# FASTAPI APP INITIALIZATION
# ============================================================================

app = FastAPI(
    title="Helix Engine Webhook Gateway",
    description="Telegram webhook interceptor + Aider automation pipeline",
    lifespan=lifespan
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def send_telegram_message(chat_id: int, text: str, max_retries: int = 2):
    """
    Route live execution notifications back via Telegram.
    Implements exponential backoff on failure.
    """
    url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=config.telegram_timeout
                )
                if response.status_code == 200:
                    logger.debug("📤 Telegram message sent", chat_id=chat_id, text_len=len(text))
                    return True
                else:
                    logger.warning("Telegram send failed", status=response.status_code, attempt=attempt + 1)
        
        except asyncio.TimeoutError:
            logger.warning("Telegram send timeout", attempt=attempt + 1)
        except Exception as e:
            logger.error("Telegram send error", error=str(e), attempt=attempt + 1)
        
        # Exponential backoff
        if attempt < max_retries - 1:
            backoff = config.retry_backoff_base ** attempt
            await asyncio.sleep(backoff)
    
    logger.error("❌ Telegram message send failed", chat_id=chat_id, max_retries=max_retries)
    return False


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root_check():
    """Liveness probe / status endpoint."""
    return {
        "status": "online",
        "engine": "Helix Engine",
        "gateway": "FastAPI",
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for k8s-style probes."""
    try:
        # Quick validation
        if not config.telegram_token or not config.gemini_api_key:
            return JSONResponse(status_code=503, content={"status": "unhealthy", "reason": "Missing credentials"})
        return {"status": "healthy"}
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@app.get("/ready")
async def readiness_check():
    """Readiness probe - checks if server can accept traffic."""
    # Add checks for dependencies: Telegram, tunnel, workspace dir, etc.
    return {"status": "ready"}


@app.get("/logs")
async def get_logs():
    """Fetch recent logs for diagnostic purposes."""
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
    """Check the status of the Aider background compilation."""
    return execution_state


@app.post("/webhook")
async def telegram_webhook_gateway(request: Request):
    """
    Core webhook interceptor.
    Captures Telegram payloads, evaluates access permissions,
    and dispatches tasks into the Aider execution loop.
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.warning("Invalid JSON payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload received.")
    
    # Extract messaging context
    if "message" not in payload:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "No message object"})
    
    message_obj = payload["message"]
    chat_id = message_obj.get("chat", {}).get("id")
    user_id = message_obj.get("from", {}).get("id")
    prompt = message_obj.get("text", "").strip()
    
    if not chat_id or not user_id:
        logger.debug("Webhook: missing metadata", payload=str(payload)[:100])
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "Missing metadata"})
    
    # 🛑 FIREWALL CHECK: Instant lockout if user ID doesn't match whitelist
    if user_id != config.allowed_user_id:
        logger.warning("🔒 Unauthorized access attempt", user_id=user_id, from_chat=chat_id)
        await send_telegram_message(chat_id, "❌ Access Denied: You are not authorized.")
        return JSONResponse(status_code=200, content={"status": "denied"})
    
    if not prompt:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "Empty prompt"})
    
    # Handle built-in diagnostic commands
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
                lines = f.readlines()[-15:]
            log_text = "".join(lines)
            if len(log_text) > 4000:
                log_text = log_text[-4000:]
            await send_telegram_message(chat_id, f"📝 Recent Logs:\n```\n{log_text}\n```")
        else:
            await send_telegram_message(chat_id, "⚠️ Log file not found.")
        return JSONResponse(status_code=200, content={"status": "logs_delivered"})
    
    logger.info("📨 Webhook received", user_id=user_id, prompt_len=len(prompt))
    
    # NEW: Triage classification to select optimal model
    selected_model = config.gemini_model  # default fallback
    if config.triage_enabled and config.deepseek_api_key:
        try:
            triage_router = get_triage_router()
            triage_result = await triage_router.classify_prompt(prompt)
            selected_model = triage_result.model
            logger.info(
                "📊 Triage complete",
                classification=triage_result.classification,
                confidence=triage_result.confidence,
                model=selected_model,
                estimated_cost=triage_result.estimated_cost
            )
        except Exception as e:
            logger.warning("Triage failed; using default model", error=str(e))
            selected_model = config.triage_fallback_model
    
    # Dispatch Aider compilation asynchronously to prevent webhook timeout
    asyncio.create_task(
        execute_aider_compilation(
            chat_id=chat_id,
            prompt=prompt,
            user_id=user_id,
            model_override=selected_model
        )
    )
    
    return JSONResponse(status_code=200, content={"status": "queued", "task": "Aider processing initiated"})


# ============================================================================
# AIDER EXECUTION LOOP
# ============================================================================

async def execute_aider_compilation(chat_id: int, prompt: str, user_id: int, model_override: Optional[str] = None):
    """
    Asynchronous compilation runner.
    - Prepares environment, resolves API routing
    - Spawns Aider subprocess with timeout
    - Captures output and routes results to Telegram
    - model_override: Optional model to use instead of config.gemini_model
    """
    async with pipeline_lock:
        try:
            logger.info("🔨 Aider execution started", user_id=user_id, prompt_len=len(prompt))
            
            # Build environment
            env = os.environ.copy()
            env["GEMINI_API_KEY"] = config.gemini_api_key
            env["GEMINI_API_BASE"] = config.gemini_api_base
            env["LITELLM_MODE"] = "production"
            
            if config.deepseek_api_key:
                env["DEEPSEEK_API_KEY"] = config.deepseek_api_key
            
            # Select model (use override if provided, else use config default)
            selected_model = model_override or config.gemini_model
            
            # Build Aider command
            aider_cmd = [
                config.aider_bin,
                "--model", selected_model,
                "--no-show-model-warnings",
                "--yes-always",
                "--no-suggest-shell-commands",
                "--no-gitignore",
                "--no-check-update",
                "--message", prompt
            ]
            
            logger.debug("Spawning aider process", cmd=aider_cmd[:3])  # Log command prefix only
            
            await send_telegram_message(chat_id, "🚀 API Credentials Verified. Spawning Aider build agent...")
            
            # Spawn process with timeout
            process = await asyncio.create_subprocess_exec(
                *aider_cmd,
                cwd=config.workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            execution_state["status"] = "running"
            execution_state["pid"] = process.pid
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=config.aider_timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                logger.error("Aider process timeout", timeout_secs=config.aider_timeout)
                await send_telegram_message(chat_id, f"⏱️ Build timeout after {config.aider_timeout}s. Process killed.")
                return
            
            output_log = stdout.decode().strip()
            error_log = stderr.decode().strip()
            
            logger.info(
                "Aider execution completed",
                returncode=process.returncode,
                stdout_len=len(output_log),
                stderr_len=len(error_log)
            )
            
            if process.returncode == 0:
                success_msg = "✨ Build successfully applied & committed!"
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


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    try:
        import uvicorn
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_config=None  # Use our structured logging
        )
    except Exception as e:
        logger.critical("Failed to start server", error=str(e), exc_info=True)
        sys.exit(1)
