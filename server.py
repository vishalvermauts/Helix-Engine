import os
import asyncio
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from lib.config import get_config
from lib.logging import get_logger
from agents.triage_router import get_triage_router
from agents.architect_agent import get_architect
from agents.ast_mapper import get_ast_mapper
from agents.snapshot_manager import get_snapshot_manager
from middleware.context_pruner import get_context_pruner
from middleware.rag_fetcher import get_rag_fetcher
from middleware.shadow_linter import get_shadow_linter
from middleware.visual_validator import get_visual_validator
from middleware.escrow_manager import get_escrow_manager
from lib.validator_agent import validate_aider_run

logger = get_logger("server")
config = get_config()

# Global state
pipeline_lock = asyncio.Lock()
execution_state = {
    "status": "idle",
    "pid": None,
    "last_run": None,
    "escrow_event": asyncio.Event(),
    "escrow_hint": ""
}
monitor_task = None

async def lifespan(app: FastAPI):
    global monitor_task
    try:
        from agents.system_monitor import SystemMonitor
        monitor = SystemMonitor()
        monitor_task = asyncio.create_task(monitor.run_daemon())
        logger.info("✅ Helix Engine startup complete", workspace=str(config.WORKSPACE_DIR))
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
    return {"status": "online", "engine": "Helix", "timestamp": datetime.utcnow().isoformat() + "Z"}

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
            return {"logs": f.readlines()[-100:]}
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
    
    if execution_state["status"] == "escrow_paused":
        execution_state["escrow_hint"] = prompt
        execution_state["escrow_event"].set()
        return JSONResponse(status_code=200, content={"status": "escrow_hint_received"})
        
    logger.info("📨 Webhook received", user_id=user_id, prompt_len=len(prompt))
    
    selected_model = config.GEMINI_MODEL
    matched_skills = []
    blueprint_context = ""
    ast_context = ""
    rag_context = ""
    
    if config.TRIAGE_ENABLED:
        triage_router = get_triage_router()
        triage_result = await triage_router.classify_prompt(prompt)
        selected_model = triage_result.model
        matched_skills = triage_result.matched_skills
        logger.info("📊 Triage complete", classification=triage_result.classification, model=selected_model, skills=len(matched_skills))
        
        # Speculative RAG Fetch
        lower_prompt = prompt.lower()
        rag_fetcher = get_rag_fetcher()
        if "tailwind" in lower_prompt:
            rag_context += await rag_fetcher.fetch_context("tailwind")
        if "react" in lower_prompt:
            rag_context += await rag_fetcher.fetch_context("react")
        
        if triage_result.classification == "COMPLEX":
            await send_telegram_message(chat_id, "🕸️ AST Mapper scanning workspace dependencies...")
            ast_mapper = get_ast_mapper()
            ast_context = ast_mapper.generate_dependency_context()

            await send_telegram_message(chat_id, "📐 Architect designing structural blueprint...")
            architect = get_architect()
            blueprint = await architect.generate_blueprint(prompt)
            if blueprint.action == "REJECT":
                logger.warning(f"Architect rejected prompt: {blueprint.reasoning}")
                await send_telegram_message(chat_id, f"❌ Request Rejected by Architect.\nReason: {blueprint.reasoning}")
                return JSONResponse(status_code=200, content={"status": "rejected"})
            
            blueprint_context = f"\n\n[ARCHITECT BLUEPRINT]\n{blueprint.instructions}\nYou may ONLY touch the following files: {', '.join(blueprint.files_to_edit) if blueprint.files_to_edit else 'None (Do not edit existing files without explicit instruction).'}\n\n"
    
    asyncio.create_task(execute_aider_compilation(chat_id, prompt, user_id, selected_model, matched_skills, blueprint_context + ast_context + rag_context))
    
    return JSONResponse(status_code=200, content={"status": "queued"})


async def execute_aider_compilation(chat_id: int, original_prompt: str, user_id: int, selected_model: str, matched_skills: list = None, blueprint_context: str = ""):
    if matched_skills is None: matched_skills = []
    
    # Create Snapshot
    snapshot_manager = get_snapshot_manager()
    snapshot_path = snapshot_manager.create_snapshot()
    if snapshot_path:
        await send_telegram_message(chat_id, "📸 Creating safety snapshot before execution...")

    async with pipeline_lock:
        current_prompt = original_prompt + blueprint_context
        max_iterations = 3
        
        try:
            iteration = 1
            while iteration <= max_iterations:
                logger.info(f"🔨 Aider execution started (Attempt {iteration}/{max_iterations})", user_id=user_id, model=selected_model)
                await send_telegram_message(chat_id, f"🚀 Executing via Helix Engine...\nModel: {selected_model}" + (f"\n🔄 Self-Correcting (Attempt {iteration}/{max_iterations})..." if iteration > 1 else ""))
                
                env = os.environ.copy()
                env["GEMINI_API_KEY"] = config.GEMINI_API_KEY
                env["GEMINI_API_BASE"] = config.GEMINI_API_BASE
                
                workspace_dir = config.WORKSPACE_DIR
                identity_path = f"{workspace_dir}/core_memory/IDENTITY.md"
                profile_path = f"{workspace_dir}/core_memory/PROFILE.md"
                
                # We spawn a strictly constrained Docker container to run Aider, keeping our host VM perfectly clean
                docker_prefix = [
                    "docker", "run", "--rm",
                    "--memory=2g", "--cpus=2",
                    "-v", f"{workspace_dir}:/workspace",
                    "-e", f"GEMINI_API_KEY={config.GEMINI_API_KEY}",
                    "-e", f"GEMINI_API_BASE={config.GEMINI_API_BASE}",
                    "-w", "/workspace",
                    "aircode-sandbox"
                ]
                
                aider_cmd = docker_prefix + [
                    "aider", # inside container it's just 'aider'
                    "--model", selected_model,
                    "--no-show-model-warnings",
                    "--yes-always",
                    "--no-suggest-shell-commands",
                    "--no-gitignore",
                    "--no-auto-commit",
                    "--no-git",
                    "--no-check-update",
                    "--read", "/workspace/core_memory/IDENTITY.md",
                    "--read", "/workspace/core_memory/PROFILE.md"
                ]
                
                for skill_path in matched_skills:
                    # make paths relative to workspace
                    rel_skill = str(Path(skill_path).relative_to(workspace_dir))
                    aider_cmd.extend(["--read", f"/workspace/{rel_skill}"])
                    
                aider_cmd.extend(["--message", current_prompt])
                
                process = await asyncio.create_subprocess_exec(
                    *aider_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                execution_state["status"] = f"running (iter {iteration})"
                execution_state["pid"] = process.pid
                
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=config.AIDER_TIMEOUT)
                except asyncio.TimeoutError:
                    process.kill()
                    logger.error("Aider process timeout")
                    await send_telegram_message(chat_id, f"⏱️ Build timeout after {config.AIDER_TIMEOUT}s.")
                    return
                
                output_log = stdout.decode('utf-8', errors='replace').strip()
                error_log = stderr.decode('utf-8', errors='replace').strip()
                
                # Shadow Linter runs automatically to fix up syntax issues
                shadow_linter = get_shadow_linter()
                linter_success, linter_out = await shadow_linter()
                if not linter_success:
                    error_log += f"\n[SHADOW LINTER FIX REQUIRED]\n{linter_out}"
                
                # Validation Step
                is_valid, corrective_feedback = await validate_aider_run(original_prompt, output_log, error_log, process.returncode)
                
                # Visual Validation (Runs after LLM Validation)
                if is_valid:
                    visual_validator = get_visual_validator()
                    vis_valid, vis_corrective = await visual_validator()
                    if not vis_valid:
                        is_valid = False
                        corrective_feedback = vis_corrective
                
                if is_valid:
                    success_msg = f"✨ Build successfully applied and verified (in {iteration} attempts)!"
                    if output_log:
                        success_msg += f"\n\n```\n{output_log[:500]}\n```"
                    await send_telegram_message(chat_id, success_msg)
                    return  # Success, exit the loop
                
                logger.warning(f"Validation failed on iteration {iteration}. Corrective feedback: {corrective_feedback}")
                if iteration < max_iterations:
                    context_pruner = get_context_pruner()
                    pruned_feedback = await context_pruner(f"Validation Error:\n{corrective_feedback}\n\nStderr:\n{error_log}")
                    # Append the corrective feedback to the prompt for the next loop
                    current_prompt = f"{pruned_feedback}\n\nPlease fix the issues and fulfill the original request: {original_prompt}"
                    iteration += 1
                else:
                    # ESCROW Logic
                    logger.warning("Max iterations reached. Triggering Escrow Pause.")
                    execution_state["status"] = "escrow_paused"
                    execution_state["escrow_event"].clear()
                    
                    escrow_manager = get_escrow_manager()
                    await escrow_manager(chat_id, corrective_feedback)
                    
                    # Wait for webhook hint
                    await execution_state["escrow_event"].wait()
                    
                    hint = execution_state.get("escrow_hint", "").strip()
                    if hint.lower() != "/abort":
                        # Resume escrow!
                        logger.info("Resuming from Escrow with user hint.")
                        current_prompt = f"User Hint: {hint}\n\nPlease fix the issues: {original_prompt}"
                        iteration = 1 # reset!
                        execution_state["status"] = "running"
                        continue
                        
                    logger.error(f"Max iterations reached. Build aborted by user.")
                    # Rollback on ultimate failure
                    if snapshot_path:
                        await send_telegram_message(chat_id, f"❌ Build failed after 3 attempts. Rolling back changes to safety snapshot...")
                        snapshot_manager.rollback_snapshot(snapshot_path)
                            
                    fail_msg = f"❌ Build failed after {max_iterations} attempts. Final validation error: {corrective_feedback}"
                    if error_log:
                        fail_msg += f"\n\n```\n{error_log[:500]}\n```"
                    await send_telegram_message(chat_id, fail_msg)
                    break                
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
