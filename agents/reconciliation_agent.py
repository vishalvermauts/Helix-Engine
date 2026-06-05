import os
import asyncio
from pathlib import Path
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("reconciliation_agent")

class ReconciliationAgent:
    def __init__(self, workspace_root: str):
        self.config = get_config()
        self.workspace_root = Path(workspace_root)

    async def resolve_conflicts(self, target_file: str) -> bool:
        logger.warning(f"⚠️ Merge conflict detected in {target_file}. Invoking Reconciliation Agent...")
        
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = self.config.GEMINI_API_KEY
        
        contract_path = self.workspace_root / "core_memory" / "contract.md"
        
        # Use high-reasoning model for conflict resolution
        aider_cmd = [
            self.config.AIDER_BIN,
            "--model", self.config.GEMINI_MODEL,
            "--no-show-model-warnings",
            "--yes-always",
            "--no-suggest-shell-commands",
            "--read", str(contract_path),
            "--message", f"Please resolve the git merge conflict markers in {target_file}. Ensure the final output strictly adheres to contract.md and preserves the core functionality of both incoming branches."
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *aider_cmd,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            
            if process.returncode == 0:
                logger.info(f"✅ Conflict in {target_file} resolved successfully by Reconciliation Agent.")
                return True
            else:
                logger.error(f"❌ Reconciliation Agent failed to resolve {target_file}")
                return False
                
        except asyncio.TimeoutError:
            process.kill()
            logger.error(f"⏱️ Reconciliation Agent timed out on {target_file}.")
            return False

def get_reconciliation_agent(workspace_root: str) -> ReconciliationAgent:
    return ReconciliationAgent(workspace_root)
