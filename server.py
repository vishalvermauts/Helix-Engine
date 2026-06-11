import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import websockets

from lib.config import get_config
from lib.logging import get_logger
from lib.config import reload_config
from agents.triage_router import get_triage_router, get_triage_stats
from agents.system_monitor import get_system_monitor
from agents.planner_agent import get_planner_agent
from agents.orchestrator import get_swarm_orchestrator

logger = get_logger("server", level="INFO", format_type="json")
config = get_config()

pipeline_lock = asyncio.Lock()
execution_state = {
    "status": "idle",
    "last_run": None,
    "pid": None,
    "current_prompt": None,
    "start_time": None,
    "blueprint": None,
    "completed_tasks": [],
    "failed_tasks": [],
    "running_task": None,
    "history": [],
    "classification": None,
    "selected_model": None
}

active_connections = set()
log_tail_task = None
monitor_task = None
system_monitor_instance = None

async def broadcast_state_update():
    if active_connections:
        payload = {"type": "status", "data": execution_state}
        await asyncio.gather(
            *[conn.send_json(payload) for conn in active_connections],
            return_exceptions=True
        )

async def tail_logs_daemon():
    log_path = Path("logs/aircode.log")
    # Wait for log file to exist
    while not log_path.exists():
        await asyncio.sleep(1)
        
    with open(log_path, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            try:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.1) # Check for new lines every 100ms
                    continue
                if active_connections:
                    payload = {"type": "log", "data": line}
                    await asyncio.gather(
                        *[conn.send_json(payload) for conn in active_connections],
                        return_exceptions=True
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Log tailing daemon error", error=str(e))
                await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task, system_monitor_instance, log_tail_task
    try:
        logger.info("🚀 Helix Engine initializing...", config=config.to_dict())
        
        if not Path(config.AIDER_BIN).exists():
            logger.warning(f"Aider binary not found at {config.AIDER_BIN}")
        
        workspace_dir = Path(config.WORKSPACE_DIR)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Start system monitor daemon
        system_monitor_instance = get_system_monitor()
        monitor_task = asyncio.create_task(system_monitor_instance.run_daemon())
        
        # Start log tailing daemon
        log_tail_task = asyncio.create_task(tail_logs_daemon())
        
        logger.info("✅ Helix Engine startup complete", workspace=str(workspace_dir))
    except Exception as e:
        logger.critical("❌ Startup failed", error=str(e), exc_info=True)
        raise
    
    yield
    
    logger.info("🛑 Helix Engine shutting down...")
    if monitor_task:
        monitor_task.cancel()
    if log_tail_task:
        log_tail_task.cancel()
    if system_monitor_instance:
        await system_monitor_instance.stop()

app = FastAPI(
    title="Helix Engine Webhook Gateway",
    description="Modern async master control tower",
    lifespan=lifespan
)

# Static mount for /workspace
static_dir = Path(config.WORKSPACE_DIR)
static_dir.mkdir(parents=True, exist_ok=True)

@app.middleware("http")
async def disable_cache_for_workspace(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/workspace"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Helix Engine Node: Online</h1>")

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_api(request: Request, path: str):
    target_url = f"http://localhost:8001/api/{path}"
    try:
        async with httpx.AsyncClient() as client:
            body = await request.body()
            headers = dict(request.headers)
            headers.pop("host", None)
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params
            )
            # Try to return JSON if valid, else raw text (wrapped in JSON for simplicity here)
            try:
                content = response.json()
            except:
                content = response.text
            return JSONResponse(status_code=response.status_code, content=content)
    except Exception as e:
        return JSONResponse(status_code=502, content={"status": "error", "message": "Backend proxy failed"})


@app.api_route("/workspace-api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_workspace_api(request: Request, path: str):
    target_url = f"http://localhost:9000/{path}"
    try:
        async with httpx.AsyncClient() as client:
            body = await request.body()
            headers = dict(request.headers)
            headers.pop("host", None)
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params,
                timeout=15.0
            )
            try:
                content = response.json()
            except:
                content = response.text
            return JSONResponse(status_code=response.status_code, content=content)
    except Exception as e:
        return JSONResponse(status_code=502, content={"status": "error", "message": f"Workspace API proxy failed: {str(e)}"})

@app.websocket("/ws")
async def websocket_proxy(websocket: WebSocket):
    await websocket.accept()
    try:
        async with websockets.connect("ws://localhost:8001/ws") as backend_ws:
            async def forward_to_backend():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await backend_ws.send(data)
                except WebSocketDisconnect:
                    pass
            
            async def forward_to_client():
                try:
                    async for message in backend_ws:
                        await websocket.send_text(message)
                except websockets.exceptions.ConnectionClosed:
                    pass
            
            await asyncio.gather(
                forward_to_backend(),
                forward_to_client()
            )
    except Exception as e:
        logger.error("WebSocket proxy error", error=str(e))


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        # Send initial state immediately
        await websocket.send_json({"type": "status", "data": execution_state})
        while True:
            # Keep connection open and listen for disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Dashboard WebSocket error", error=str(e))
    finally:
        active_connections.discard(websocket)


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


@app.get("/stats/triage")
async def get_triage_stats_endpoint():
    """Phase 4/5: Return in-session triage routing statistics as JSON."""
    stats = get_triage_stats()
    return stats.summary_dict()


@app.post("/admin/reload-config")
async def admin_reload_config():
    """
    Phase 5: Hot-reload .env without restarting the server.

    This lets you change TRIAGE_CANARY_RATE, TRIAGE_ENABLED, or any other
    env var in .env and have it take effect immediately for the next request.
    Note: the triage_stats singleton is NOT reset — only the config singleton
    is refreshed.
    """
    global config
    try:
        config = reload_config()
        logger.info("🔄 Config hot-reloaded", triage_enabled=config.TRIAGE_ENABLED,
                    canary_rate=config.TRIAGE_CANARY_RATE)
        return {
            "status": "reloaded",
            "triage_enabled": config.TRIAGE_ENABLED,
            "triage_canary_rate": config.TRIAGE_CANARY_RATE,
            "triage_stats_interval": config.TRIAGE_STATS_INTERVAL,
            "gemini_model": config.GEMINI_MODEL,
        }
    except Exception as e:
        logger.error("Config reload failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Config reload failed: {e}")


@app.post("/admin/reset-stats")
async def admin_reset_stats():
    """
    Phase 5: Reset the in-memory TriageStats singleton to a fresh baseline.

    Use this between canary windows for clean A/B cost comparisons:
      1. Set TRIAGE_CANARY_RATE=0.1  →  POST /admin/reload-config  →  POST /admin/reset-stats
      2. Let traffic run for N minutes
      3. GET /stats/triage — record canary metrics
      4. POST /admin/reset-stats
      5. Set TRIAGE_CANARY_RATE=1.0  →  POST /admin/reload-config
      6. Let traffic run for the same N minutes
      7. GET /stats/triage — compare full-triage metrics vs canary
    """
    import agents.triage_router as _tr
    old = _tr._triage_stats.summary_dict()
    _tr._triage_stats = _tr.TriageStats()  # Replace singleton with fresh instance
    logger.info("🔄 TriageStats reset", previous_total=old["total_classified"])
    return {
        "status": "reset",
        "previous_session": old,
        "message": "TriageStats singleton replaced. New measurement session started.",
    }


@app.get("/admin/config")
async def admin_get_config():
    """Return the current live config with secrets redacted — useful for verifying hot-reloads."""
    return config.to_dict()


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
    
    # Phase 4: on-demand triage stats report
    if prompt.lower() in ["/triage", "triage"]:
        if system_monitor_instance:
            report = await system_monitor_instance.send_triage_report()
        else:
            from agents.triage_router import get_triage_stats as _gts
            stats = _gts()
            report = str(stats.summary_dict())
            await send_telegram_message(chat_id, report)
        return JSONResponse(status_code=200, content={"status": "triage_stats_delivered"})

    # Phase 5: detailed cost analysis report (alias for /triage with extra detail)
    if prompt.lower() in ["/cost-report", "cost-report", "/costreport"]:
        stats = get_triage_stats()
        s = stats.summary_dict()
        baseline = s["total_classified"] * 0.005
        actual = s["total_cost_usd"]
        lines = [
            "💹 *Cost Analysis Report*",
            "",
            f"Total requests : {s['total_classified']}",
            f"Canary bypassed: {s.get('canary_bypassed', 0)}",
            "",
            "*Breakdown by type:*",
            f"  SIMPLE           → {s['counts'].get('SIMPLE', 0)} × $0.0001 = ${s['counts'].get('SIMPLE', 0) * 0.0001:.4f}",
            f"  COMPLEX          → {s['counts'].get('COMPLEX', 0)} × $0.0050 = ${s['counts'].get('COMPLEX', 0) * 0.005:.4f}",
            f"  AGENT_GENERATION → {s['counts'].get('AGENT_GENERATION', 0)} × $0.0050 = ${s['counts'].get('AGENT_GENERATION', 0) * 0.005:.4f}",
            f"  QA_TESTING       → {s['counts'].get('QA_TESTING', 0)} × $0.0050 = ${s['counts'].get('QA_TESTING', 0) * 0.005:.4f}",
            "",
            f"Actual spend   : ${actual:.4f}",
            f"Baseline (all Gemini): ${baseline:.4f}",
            f"💰 Saved          : ${s['estimated_savings_usd']:.4f} ({round(100 * s['estimated_savings_usd'] / max(0.0001, baseline), 1)}%)",
            f"⚡ Simple ratio   : {s['simple_ratio_pct']}%",
            f"🏆 Peak SIMPLE/hr : {s.get('peak_simple_per_hour', 0):.1f}",
        ]
        await send_telegram_message(chat_id, "\n".join(lines))
        return JSONResponse(status_code=200, content={"status": "cost_report_delivered"})
    
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
        start_time = datetime.utcnow()
        execution_state["status"] = "planning"
        execution_state["pid"] = os.getpid()
        execution_state["current_prompt"] = prompt
        execution_state["start_time"] = start_time.isoformat() + "Z"
        execution_state["blueprint"] = None
        execution_state["completed_tasks"] = []
        execution_state["failed_tasks"] = []
        execution_state["running_task"] = None
        execution_state["classification"] = classification
        execution_state["selected_model"] = selected_model
        await broadcast_state_update()
        
        try:
            logger.info("🔨 Phase 6 Execution started", user_id=user_id)
            await send_telegram_message(chat_id, f"🚀 Executing via Helix Engine Phase 6 Grid...")
            
            workspace_dir = str(Path(config.WORKSPACE_DIR))
            planner = get_planner_agent()
            orchestrator = get_swarm_orchestrator(workspace_dir)
            
            # Setup dynamic callbacks on orchestrator to feed task progress to dashboard
            def on_task_start(task_id: str):
                execution_state["running_task"] = task_id
                asyncio.create_task(broadcast_state_update())
                
            def on_task_complete(task_id: str):
                if task_id not in execution_state["completed_tasks"]:
                    execution_state["completed_tasks"].append(task_id)
                if execution_state["running_task"] == task_id:
                    execution_state["running_task"] = None
                asyncio.create_task(broadcast_state_update())
                    
            def on_task_fail(task_id: str):
                if task_id not in execution_state["failed_tasks"]:
                    execution_state["failed_tasks"].append(task_id)
                if execution_state["running_task"] == task_id:
                    execution_state["running_task"] = None
                asyncio.create_task(broadcast_state_update())

            orchestrator.on_task_start = on_task_start
            orchestrator.on_task_complete = on_task_complete
            orchestrator.on_task_fail = on_task_fail
            
            # Step 1: Planning
            blueprint = await planner.generate(prompt, task_type=classification, matched_skills=matched_skills)
            execution_state["blueprint"] = blueprint.dict() if hasattr(blueprint, 'dict') else blueprint.model_dump()
            await broadcast_state_update()
            
            await send_telegram_message(chat_id, f"📝 Planner generated {len(blueprint.tasks)} tasks. Launching Swarm Workers...")
            
            execution_state["status"] = "running_swarm"
            await broadcast_state_update()
            
            # Step 2: Swarm Execution — pass the triage-selected model so workers
            # use it instead of falling back to the config default.
            logger.info("🧠 Swarm dispatching", model=selected_model, classification=classification)
            success = await orchestrator.execute(blueprint, selected_model=selected_model)
            
            # Add to history
            duration_sec = (datetime.utcnow() - start_time).total_seconds()
            output_url = None
            if success and system_monitor_instance and system_monitor_instance.active_tunnel_url:
                output_url = f"{system_monitor_instance.active_tunnel_url}/workspace/index.html"
                
            run_history_item = {
                "prompt": prompt,
                "start_time": execution_state["start_time"],
                "duration_seconds": round(duration_sec, 1),
                "status": "success" if success else "failed",
                "output_url": output_url,
                "classification": classification,
                "selected_model": selected_model
            }
            execution_state["history"].append(run_history_item)
            await broadcast_state_update()
            
            if success:
                success_msg = "✨ Swarm Execution completed successfully!"
                if output_url:
                    success_msg += f"\n\n🌐 View your built UI here:\n{output_url}"
                await send_telegram_message(chat_id, success_msg)
            else:
                fail_msg = "❌ Swarm Execution finished with errors. Some tasks failed."
                await send_telegram_message(chat_id, fail_msg)
                
        except Exception as e:
            logger.error("Swarm execution error", error=str(e), exc_info=True)
            await send_telegram_message(chat_id, f"⚠️ Build pipeline failed: {str(e)[:100]}")
            # Add failure to history
            duration_sec = (datetime.utcnow() - start_time).total_seconds()
            execution_state["history"].append({
                "prompt": prompt,
                "start_time": execution_state["start_time"],
                "duration_seconds": round(duration_sec, 1),
                "status": "failed",
                "output_url": None,
                "classification": classification,
                "selected_model": selected_model
            })
            await broadcast_state_update()
        finally:
            execution_state["status"] = "idle"
            execution_state["pid"] = None
            execution_state["last_run"] = datetime.utcnow().isoformat() + "Z"
            execution_state["current_prompt"] = None
            execution_state["start_time"] = None
            execution_state["blueprint"] = None
            execution_state["running_task"] = None
            await broadcast_state_update()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, reload=False, log_config=None)
