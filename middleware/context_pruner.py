import google.generativeai as genai
from pydantic import BaseModel, Field
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("context_pruner")
config = get_config()

genai.configure(api_key=config.GEMINI_API_KEY)
# We use gemini-2.5-flash since this is a fast, cheap summarizing task
model = genai.GenerativeModel("gemini-2.5-flash")

class PrunedContext(BaseModel):
    summary: str = Field(description="A very concise, 2-3 sentence summary of the previous failed attempts, focusing ONLY on what was tried and why it failed.")

async def prune_execution_context(raw_logs: str) -> str:
    """
    Compresses a massive block of previous iteration logs (errors, diffs, validator complaints)
    into a dense, token-efficient summary.
    """
    if len(raw_logs) < 1000:
        return raw_logs # No need to prune small logs
        
    prompt = f"""
    You are an expert Context Pruner.
    Below is a bloated log of a coding agent's previous failed attempts to complete a task.
    Your job is to compress this down to a single concise paragraph so the agent doesn't suffer from context bloat.
    Focus strictly on:
    1. What the agent tried to do.
    2. Why the validator rejected it (the exact error).
    
    Raw Logs:
    {raw_logs}
    """
    
    try:
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=PrunedContext,
                temperature=0.0
            )
        )
        import json
        result = json.loads(response.text)
        logger.info(f"✂️ Context pruned from {len(raw_logs)} chars to {len(result['summary'])} chars.")
        return f"[PREVIOUS ATTEMPTS SUMMARY]\n{result['summary']}\n"
    except Exception as e:
        logger.error(f"Context Pruner failed: {e}")
        return raw_logs

def get_context_pruner():
    return prune_execution_context
