import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from lib.config import get_config
from lib.logging import get_logger
from agents.triage_router import get_triage_router
from agents.system_monitor import get_system_monitor
from agents.planner_agent import get_planner_agent
from agents.orchestrator import get_swarm_orchestrator

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
    classification = "COMPLEX"
    matched_skills = []
    
    if config.TRIAGE_ENABLED:
        triage_router = get_triage_router()
        triage_result = await triage_router.classify_prompt(prompt)
        selected_model = triage_result.model
        classification = triage_result.classification
        matched_skills = triage_result.matched_skills
        logger.info("📊 Triage complete", classification=triage_result.classification, model=selected_model)
    
    asyncio.create_task(execute_aider_compilation(chat_id, prompt, user_id, selected_model, classification, matched_skills))
    
    return JSONResponse(status_code=200, content={"status": "queued"})


async def execute_aider_compilation(chat_id: int, prompt: str, user_id: int, selected_model: str, classification: str = "COMPLEX", matched_skills: list = None):
    async with pipeline_lock:
        try:
            logger.info("🔨 Phase 6 Execution started", user_id=user_id)
            await send_telegram_message(chat_id, f"🚀 Executing via Helix Engine Phase 6 Grid...")
            
            workspace_dir = str(Path(config.WORKSPACE_DIR) / "workspace")
            planner = get_planner_agent()
            orchestrator = get_swarm_orchestrator(workspace_dir)
            
            execution_state["status"] = "planning"
            execution_state["pid"] = os.getpid()
            
            # Step 1: Planning
            blueprint = await planner.generate(prompt, task_type=classification, matched_skills=matched_skills)
            await send_telegram_message(chat_id, f"📝 Planner generated {len(blueprint.tasks)} tasks. Launching Swarm Workers...")
            
            execution_state["status"] = "running_swarm"
            
            # Step 2: Swarm Execution
            success = await orchestrator.execute(blueprint)
            
            if success:
                success_msg = "✨ Swarm Execution completed successfully!"
                await send_telegram_message(chat_id, success_msg)
            else:
                fail_msg = "❌ Swarm Execution finished with errors. Some tasks failed."
                await send_telegram_message(chat_id, fail_msg)
                
        except Exception as e:
            logger.error("Swarm execution error", error=str(e), exc_info=True)
            await send_telegram_message(chat_id, f"⚠️ Build pipeline failed: {str(e)[:100]}")
        finally:
            execution_state["status"] = "idle"
            execution_state["pid"] = None
            execution_state["last_run"] = datetime.utcnow().isoformat() + "Z"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.PORT, reload=False, log_config=None)
