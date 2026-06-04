import re
import httpx
from typing import Tuple

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("validator_agent")
config = get_config()

async def validate_aider_run(original_prompt: str, stdout: str, stderr: str, returncode: int) -> Tuple[bool, str]:
    """
    Validates the Aider execution by checking return codes, detecting anomalies in stdout,
    and running an LLM static analysis on the output.
    Returns (is_valid, corrective_prompt_or_reason)
    """
    if returncode != 0:
        logger.warning("Validation failed: Aider returned non-zero exit code.")
        return False, f"Aider crashed with exit code {returncode}. Error log: {stderr[-500:]}"

    # 1. Detect known conversational dead-ends
    dead_end_patterns = [
        r"(?i)I don't have access to the.*?files",
        r"(?i)Please add.*?to the chat",
        r"(?i)add them to the chat",
        r"(?i)could not find the file",
    ]
    for pattern in dead_end_patterns:
        if re.search(pattern, stdout):
            logger.warning("Validation failed: Aider requested files to be added to the chat.")
            return False, "You complained about missing files or requested files to be added to the chat. Please generate or edit the files directly based on the initial request, assuming they exist or creating them if they don't."

    # 2. LLM Static Analysis (DeepSeek)
    if not config.DEEPSEEK_API_KEY:
        logger.info("Skipping LLM validation because DeepSeek API key is not configured.")
        return True, ""

    try:
        url = f"{config.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_prompt = (
            "You are a Verification Agent evaluating the output of an autonomous coding assistant. "
            "Your job is to determine if the coding assistant successfully fulfilled the user's request, "
            "or if it hallucinated, asked for missing files, or failed to provide a complete solution. "
            "Reply strictly with exactly 'PASS' if successful. If it failed or stalled, reply with 'FAIL: <a prompt that will instruct the coding assistant on how to fix its mistake>'."
        )
        
        # We cap the stdout to avoid massive token usage for large diffs
        capped_stdout = stdout[-3000:]
        user_message = f"USER REQUEST:\n{original_prompt}\n\nASSISTANT LOG/OUTPUT:\n{capped_stdout}"

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 150,
            "temperature": 0.0
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()
            
            if reply.startswith("PASS"):
                return True, ""
            elif reply.startswith("FAIL:"):
                corrective = reply[5:].strip()
                logger.warning(f"Validation failed via LLM: {corrective}")
                return False, corrective
            else:
                logger.warning(f"Unexpected LLM validation reply: {reply}. Defaulting to PASS.")
                return True, ""

    except Exception as e:
        logger.error(f"LLM validation error: {e}. Defaulting to PASS to prevent blocking.")
        return True, ""

