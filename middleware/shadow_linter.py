import asyncio
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("shadow_linter")
config = get_config()

async def run_shadow_linter():
    """
    Spawns an ephemeral Docker sandbox, mounts the workspace, and runs
    auto-formatters/linters directly on the codebase.
    """
    workspace_dir = config.WORKSPACE_DIR

    # We use --rm for ephemeral containers, -v to mount the workspace,
    # and restrict resources and network as requested by the user.
    cmd = [
        "docker", "run", "--rm",
        "--memory=2g", "--cpus=2",
        "--network=none",
        "-v", f"{workspace_dir}:/workspace",
        "aircode-sandbox",
        "sh", "-c", "npx prettier --write . && npx eslint --fix . --no-error-on-unmatched-pattern"
    ]
    
    logger.info("🕵️‍♂️ Shadow Linter scanning and fixing code in Ephemeral Sandbox...")
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.warning(f"Shadow Linter reported issues or failed: {stderr.decode()}")
            return False, stderr.decode()
            
        logger.info("✨ Shadow Linter applied micro-fixes successfully!")
        return True, stdout.decode()
    except Exception as e:
        logger.error(f"Failed to execute Shadow Linter: {e}")
        return False, str(e)

def get_shadow_linter():
    return run_shadow_linter
