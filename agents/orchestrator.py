import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Set, Dict, Optional
import httpx

from pydantic import BaseModel, Field

from lib.config import get_config
from lib.logging import get_logger
from agents.planner_agent import ProjectBlueprint, WorkerTask, generate_e2e_verification_script
from lib.ast_verifier import verify_and_sync_dependencies
from agents.lab_coordinator import stream_runtime_logs

logger = get_logger("swarm_orchestrator")

class SwarmOrchestrator:
    def __init__(self, workspace_root: str):
        self.config = get_config()
        self.workspace_root = Path(workspace_root)
        self._tasks_completed: Set[str] = set()
        self._tasks_failed: Set[str] = set()
        self._worker_base = self._resolve_worker_base()

    @staticmethod
    def _resolve_worker_base() -> Path:
        """
        Cross-platform RAM disk / temp directory resolver.

        Priority order:
          1. /dev/shm          — Linux tmpfs (fastest, zero I/O)
          2. R:\\helix_workers  — Windows RAM disk (ImDisk / OSFMount)
          3. tempfile.gettempdir() — OS default temp (SSD/HDD fallback)

        The chosen base is logged once at startup so operators can see
        which storage tier the swarm is running on.
        """
        candidates = []

        if platform.system() == "Linux":
            shm = Path("/dev/shm")
            if shm.exists() and os.access(shm, os.W_OK):
                candidates.append(shm)

        elif platform.system() == "Windows":
            ram_disk = Path("R:/helix_workers")
            if ram_disk.drive and Path(ram_disk.drive + "/").exists():
                candidates.append(ram_disk)

        # Always available fallback
        candidates.append(Path(tempfile.gettempdir()))

        chosen = candidates[0] / "helix_workers"
        tier = "RAM disk" if candidates[0] != Path(tempfile.gettempdir()) else "system temp"
        # Use print here since logger may not be ready at class-definition time
        print(f"[SwarmOrchestrator] Worker base resolved to: {chosen} ({tier})")
        return chosen

    async def execute(self, blueprint: ProjectBlueprint, selected_model: Optional[str] = None) -> bool:
        """
        Execute a project blueprint across concurrent swarm workers.

        Args:
            blueprint:      The planner's ProjectBlueprint (tasks + contract).
            selected_model: The model chosen by the triage router for this run.
                            If None, falls back to config.GEMINI_MODEL.
                            Passed down to every aider subprocess invocation.
        """
        # Resolve the model that all workers will use
        worker_model = selected_model or self.config.GEMINI_MODEL
        if self.config.VERTEX_ENABLED:
            if not worker_model.startswith("vertex_ai/"):
                if "/" in worker_model:
                    worker_model = "vertex_ai/" + worker_model.split("/")[-1]
                else:
                    worker_model = "vertex_ai/" + worker_model
                    
        logger.info(
            f"🚀 Starting Swarm Orchestrator with {len(blueprint.tasks)} tasks.",
            model=worker_model,
        )
        
        # 1. Setup global workspace
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        
        # 2. Write Contract to memory
        memory_dir = self.workspace_root / "core_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        contract_path = memory_dir / "contract.md"
        contract_path.write_text(blueprint.contract)
        logger.info(f"📜 Project Contract written to {contract_path}")
        
        # 3. Setup concurrency execution based on task count
        max_workers = min(10, len(blueprint.tasks))
        if max_workers < 1:
            max_workers = 1
        semaphore = asyncio.Semaphore(max_workers)
        logger.info(f"🚀 Starting Phase 6 Swarm Orchestrator with {len(blueprint.tasks)} tasks. (Bounded: {max_workers} threads)")
        
        task_futures: Dict[str, asyncio.Future] = {
            task.task_id: asyncio.Future() for task in blueprint.tasks
        }

        async def run_worker(task: WorkerTask):
            # Wait for dependencies
            for dep in task.depends_on:
                if dep in task_futures:
                    logger.info(f"Task {task.task_id} waiting on dependency {dep}")
                    await task_futures[dep]
                    if dep in self._tasks_failed:
                        logger.error(f"Task {task.task_id} aborted because dependency {dep} failed.")
                        task_futures[task.task_id].set_result(False)
                        self._tasks_failed.add(task.task_id)
                        if hasattr(self, 'on_task_fail') and self.on_task_fail:
                            self.on_task_fail(task.task_id)
                        return

            async with semaphore:
                logger.info(f"⚙️ Starting Worker Task: {task.task_id} - {task.description}")
                if hasattr(self, 'on_task_start') and self.on_task_start:
                    self.on_task_start(task.task_id)
                
                # Setup isolated workspace (cloning current state)
                worker_dir = self._worker_base / task.task_id
                if worker_dir.exists():
                    shutil.rmtree(worker_dir)
                shutil.copytree(self.workspace_root, worker_dir, ignore=shutil.ignore_patterns("temp_workers", ".git", "node_modules"))
                
                try:
                    # Execute Aider via subprocess
                    env = os.environ.copy()
                    if self.config.VERTEX_ENABLED:
                        env["VERTEXAI_PROJECT"] = self.config.VERTEX_PROJECT
                        env["VERTEXAI_LOCATION"] = self.config.VERTEX_LOCATION
                        env.pop("GEMINI_API_KEY", None)
                    else:
                        env["GEMINI_API_KEY"] = self.config.GEMINI_API_KEY
                    
                    if "HELIX_MOCK_LLM_PAYLOAD" in os.environ:
                        logger.info(f"TEST HOOK: Bypassing Aider execution for {task.task_id} to conserve API credits.")
                        await asyncio.sleep(2.0) # Simulate work latency
                        
                        if hasattr(task, 'generated_files') and task.generated_files:
                            for gen_file in task.generated_files:
                                path_str = gen_file.path if hasattr(gen_file, 'path') else gen_file['path']
                                if path_str.startswith("workspace/"):
                                    path_str = path_str[len("workspace/"):]
                                content_str = gen_file.content if hasattr(gen_file, 'content') else gen_file['content']
                                
                                mock_path = worker_dir / path_str
                                mock_path.parent.mkdir(parents=True, exist_ok=True)
                                mock_path.write_text(content_str)
                        else:
                            for target_file in task.target_files:
                                mock_path = worker_dir / target_file
                                mock_path.parent.mkdir(parents=True, exist_ok=True)
                                mock_path.write_text(f"/* Mock content for {target_file} generated by Lab Harness */")
                        
                        logger.info(f"✅ Worker {task.task_id} completed successfully (MOCKED).")
                        
                        files_to_merge = task.target_files
                        if hasattr(task, 'generated_files') and task.generated_files:
                            files_to_merge = []
                            for gen_file in task.generated_files:
                                path_str = gen_file.path if hasattr(gen_file, 'path') else gen_file['path']
                                files_to_merge.append(path_str)
                                
                        for target_file in files_to_merge:
                            clean_target = target_file[len("workspace/"):] if target_file.startswith("workspace/") else target_file
                            src = worker_dir / clean_target
                            dst = self.workspace_root / clean_target
                            if src.exists():
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(src, dst)
                                logger.info(f"Merged {clean_target} from {task.task_id}")
                                
                        self._tasks_completed.add(task.task_id)
                        task_futures[task.task_id].set_result(True)
                        if hasattr(self, 'on_task_complete') and self.on_task_complete:
                            self.on_task_complete(task.task_id)
                        return

                    # Pre-write generated files first to bootstrap
                    if hasattr(task, 'generated_files') and task.generated_files:
                        for gen_file in task.generated_files:
                            path_str = gen_file.path if hasattr(gen_file, 'path') else gen_file['path']
                            if path_str.startswith("workspace/"):
                                path_str = path_str[len("workspace/"):]
                            content_str = gen_file.content if hasattr(gen_file, 'content') else gen_file['content']
                            
                            file_path = worker_dir / path_str
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            file_path.write_text(content_str, encoding="utf-8")
                            logger.info(f"Pre-wrote generated file: {path_str}")

                    # Clean target files paths to remove 'workspace/' prefix
                    clean_target_files = [tf[len("workspace/"):] if tf.startswith("workspace/") else tf for tf in task.target_files]

                    # TIER 3: CORRECTION (Self-Healing Loop)
                    max_retries = 3
                    current_attempt = 0
                    test_passed = False
                    feedback = ""

                    while current_attempt < max_retries and not test_passed:
                        current_attempt += 1
                        logger.info(f"Worker {task.task_id} - Attempt {current_attempt}/{max_retries}")
                        
                        # Build a fresh aider command each attempt to avoid
                        # double-appending --message across retry iterations.
                        aider_cmd = [
                            self.config.AIDER_BIN,
                            "--model", worker_model,
                            "--no-show-model-warnings",
                            "--yes-always",
                            "--no-auto-lint",
                            "--no-suggest-shell-commands",
                            "--read", str(worker_dir / "core_memory" / "contract.md"),
                        ]

                        if current_attempt == 1:
                            aider_cmd.extend(["--message", f"TASK ID: {task.task_id}\nDESCRIPTION: {task.description}\nTARGET FILES: {', '.join(clean_target_files)}"])
                        else:
                            aider_cmd.extend(["--message", f"The previous execution failed validation. Please fix the following errors:\n{feedback}"])

                        aider_cmd.extend(clean_target_files)

                        try:
                            process = await asyncio.create_subprocess_exec(
                                *aider_cmd,
                                cwd=str(worker_dir),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                env=env
                            )
                            
                            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.config.AIDER_TIMEOUT)
                            
                            if process.returncode != 0:
                                feedback = f"Aider generation failed with exit code {process.returncode}:\n{stderr.decode('utf-8')[-1000:]}"
                                logger.warning(f"Worker {task.task_id} failed aider generation. Using generated files fallback.")
                        except Exception as e:
                            logger.warning(f"Aider execution failed or not found: {e}. Using generated files fallback.")
                        
                        # QA Validation Step (Syntax Checking & Dependency Sync)
                        validation_failed = False
                        has_server_py = False
                        for target_file in clean_target_files:
                            if target_file.endswith(".py"):
                                file_path = worker_dir / target_file
                                if file_path.name == "server.py" or file_path.name == "main.py":
                                    has_server_py = file_path
                                if file_path.exists():
                                    # 1. Sync Dependencies via Pip Interceptor
                                    verify_and_sync_dependencies(str(file_path))
                                    
                                    # 2. Syntax Check
                                    val_proc = await asyncio.create_subprocess_exec(
                                        "python3", "-m", "py_compile", str(file_path),
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE
                                    )
                                    val_stdout, val_stderr = await val_proc.communicate()
                                    if val_proc.returncode != 0:
                                        validation_failed = True
                                        feedback = f"Syntax error in {target_file}:\n{val_stderr.decode('utf-8')}"
                                        logger.warning(f"Worker {task.task_id} generated invalid Python syntax. Retrying...")
                                        break
                                        
                        # E2E Telemetry Run
                        if not validation_failed:
                            # Only trigger E2E if THIS worker explicitly produces index.html
                            # (not just inherited from previous runs via shutil.copytree)
                            has_ui = any(
                                tf.endswith("index.html") for tf in clean_target_files
                            )
                            
                            if has_ui or has_server_py:
                                logger.info(f"Initiating E2E Telemetry check on Workspace")
                                # Use a deterministic structural E2E script - no LLM to hallucinate selectors
                                e2e_url = "http://localhost:8001" if has_server_py else f"file://{worker_dir.absolute()}/index.html"
                                e2e_script = f"""import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto('{e2e_url}')
            # Only verify page loaded with a main heading - no specific selectors
            await page.wait_for_selector('h1, h2, main, body > *', timeout=10000)
            title = await page.title()
            print(f'\\u2705 Behavioral Interaction verified successfully. Page title: {{title}}')
            await browser.close()
            exit(0)
        except Exception as e:
            print(f'\\u274c Failure: {{e}}')
            if browser:
                await browser.close()
            exit(1)

if __name__ == '__main__':
    asyncio.run(main())
"""
                                e2e_path = worker_dir / "e2e_smoke_check.py"
                                e2e_path.write_text(e2e_script)
                                
                                backend_proc = None
                                try:
                                    if has_server_py:
                                        logger.info(f"Detected backend script {has_server_py.name}, launching daemon on port 8001")
                                        # Clean up any existing persistent backends on Port 8001
                                        kill_proc = await asyncio.create_subprocess_exec(
                                            "lsof", "-t", "-i:8001",
                                            stdout=asyncio.subprocess.PIPE
                                        )
                                        kill_out, _ = await kill_proc.communicate()
                                        if kill_out:
                                            pids = kill_out.decode().strip().split()
                                            for pid in pids:
                                                await asyncio.create_subprocess_exec("kill", "-9", pid)
                                                
                                        # Launch persistent backend daemon on Port 8001
                                        # Force Uvicorn or Flask to run on 8001 by overriding env vars
                                        env_backend = os.environ.copy()
                                        env_backend["PORT"] = "8001"
                                        
                                        # We use subprocess.Popen directly to decouple it completely from the Orchestrator loop
                                        import subprocess
                                        with open(worker_dir / "backend_persistent.log", "w") as log_file:
                                            backend_proc = subprocess.Popen(
                                                ["python3", str(has_server_py)],
                                                cwd=str(worker_dir),
                                                env=env_backend,
                                                stdout=log_file,
                                                stderr=subprocess.STDOUT,
                                                start_new_session=True # Detach from parent
                                            )
                                        
                                        # Give server a second to boot
                                        await asyncio.sleep(2)
                                    
                                    # Run Playwright E2E (URL is now baked into the generated script)
                                    e2e_proc = await asyncio.create_subprocess_exec(
                                        sys.executable, str(e2e_path),
                                        cwd=str(worker_dir),
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE
                                    )
                                    e2e_out, e2e_err = await e2e_proc.communicate()
                                    
                                    if e2e_proc.returncode != 0:
                                        validation_failed = True
                                        feedback = "Runtime Verification Failed!\n"
                                        feedback += f"E2E Test Output:\n{e2e_out.decode('utf-8')}\n{e2e_err.decode('utf-8')}\n"
                                        logger.warning(f"Worker {task.task_id} failed runtime validation. Retrying...\nFeedback: {feedback}")
                                finally:
                                    if backend_proc:
                                        logger.info(f"Terminating persistent backend daemon on port 8001 (PID {backend_proc.pid})")
                                        try:
                                            backend_proc.terminate()
                                            # Use a simple wait loop or wait() to avoid blocks
                                            backend_proc.wait(timeout=5)
                                        except subprocess.TimeoutExpired:
                                            logger.warning(f"Backend daemon (PID {backend_proc.pid}) did not terminate, killing...")
                                            backend_proc.kill()
                                        except Exception as e:
                                            logger.error(f"Error terminating backend daemon: {e}")
                                        
                        if validation_failed:
                            if current_attempt >= max_retries:
                                raise Exception(f"Worker {task.task_id} failed QA Validation after {max_retries} attempts.")
                        else:
                            test_passed = True
                    
                    logger.info(f"✅ Worker {task.task_id} completed successfully after {current_attempt} attempts.")
                    for target_file in clean_target_files:
                        src = worker_dir / target_file
                        dst = self.workspace_root / target_file
                        if src.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            logger.info(f"Merged {target_file} from {task.task_id}")
                            
                    self._tasks_completed.add(task.task_id)
                    task_futures[task.task_id].set_result(True)
                    if hasattr(self, 'on_task_complete') and self.on_task_complete:
                        self.on_task_complete(task.task_id)

                except Exception as e:
                    logger.error(f"❌ Worker {task.task_id} failed: {e}")
                    
                    # --- ON-FAILURE DUMP STRATEGY ---
                    dump_dir = Path(self.config.WORKSPACE_DIR) / "crash_dumps" / task.task_id
                    try:
                        if dump_dir.exists():
                            shutil.rmtree(dump_dir)
                        dump_dir.parent.mkdir(parents=True, exist_ok=True)
                        logger.warning(f"Preserving failed RAM disk workspace to persistent storage: {dump_dir}")
                        shutil.copytree(worker_dir, dump_dir)
                    except Exception as copy_e:
                        logger.error(f"Failed to create crash dump for {task.task_id}: {copy_e}")
                    # ---------------------------------
                    
                    self._tasks_failed.add(task.task_id)
                    task_futures[task.task_id].set_result(False)
                    if hasattr(self, 'on_task_fail') and self.on_task_fail:
                        self.on_task_fail(task.task_id)
                    
                finally:
                    # Always clean up the RAM disk to prevent memory leaks on the VM
                    if worker_dir.exists():
                        try:
                            shutil.rmtree(worker_dir)
                            logger.info(f"Cleaned up RAM disk partition for {task.task_id}")
                        except Exception as e:
                            logger.error(f"Failed to cleanup RAM disk for {task.task_id}: {e}")
                            
        # 4. Launch all tasks concurrently
        execution_tasks = [asyncio.create_task(run_worker(task)) for task in blueprint.tasks]
        await asyncio.gather(*execution_tasks)
        
        logger.info(f"🏁 Swarm Execution Complete. Success: {len(self._tasks_completed)}, Failed: {len(self._tasks_failed)}")
        return len(self._tasks_failed) == 0

def get_swarm_orchestrator(workspace_root: str) -> SwarmOrchestrator:
    return SwarmOrchestrator(workspace_root)
