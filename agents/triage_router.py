import re
import httpx
from typing import Optional, List
from pydantic import BaseModel, Field

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("triage_router")
config = get_config()

class TriageResult(BaseModel):
    classification: str = Field(..., description="Either SIMPLE or COMPLEX")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    model: str = Field(..., description="The LLM model to be used based on classification")
    estimated_cost: str = Field(default="unknown")

class TriageRouter:
    def __init__(self):
        self.config = get_config()
        self.simple_keywords = ["typo", "readme", "comment", "lint", "format", "rename"]
        self.complex_keywords = ["scaffold", "database", "refactor", "architecture", "design", "async"]

    async def classify_prompt(self, prompt: str) -> TriageResult:
        # 1. Manual Overrides
        if "[FORCE_SIMPLE]" in prompt:
            logger.info("Manual override detected: [FORCE_SIMPLE]")
            return TriageResult(classification="SIMPLE", confidence=1.0, model="gemini/gemini-2.5-flash", estimated_cost="low")
        if "[FORCE_COMPLEX]" in prompt:
            logger.info("Manual override detected: [FORCE_COMPLEX]")
            return TriageResult(classification="COMPLEX", confidence=1.0, model=self.config.GEMINI_MODEL, estimated_cost="high")

        # 2. DeepSeek V3 API Hook
        if not self.config.DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API Key missing, falling back to local heuristic.")
            return self._local_fallback(prompt)

        try:
            url = f"{self.config.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a routing agent. Reply with exactly one word: 'SIMPLE' if the user request is a minor formatting, typo, or comment change. Reply 'COMPLEX' if it involves architecture, scaffolding, logic changes, or refactoring."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 10,
                "temperature": 0.0
            }

            async with httpx.AsyncClient(timeout=self.config.TRIAGE_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                reply = data["choices"][0]["message"]["content"].strip().upper()
                
                if "SIMPLE" in reply:
                    return TriageResult(classification="SIMPLE", confidence=0.9, model="gemini/gemini-2.5-flash", estimated_cost="low")
                elif "COMPLEX" in reply:
                    return TriageResult(classification="COMPLEX", confidence=0.9, model=self.config.GEMINI_MODEL, estimated_cost="high")
                else:
                    logger.warning(f"Unexpected DeepSeek reply: {reply}")
                    return self._local_fallback(prompt)

        except httpx.TimeoutException:
            logger.warning("DeepSeek API timeout (1.5s exceeded). Using local fallback.")
            return self._local_fallback(prompt)
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}. Using local fallback.")
            return self._local_fallback(prompt)

    def _local_fallback(self, prompt: str) -> TriageResult:
        """Local fast-path keyword scan fallback."""
        prompt_lower = prompt.lower()
        
        # Check complex first as it's safer to overestimate
        for kw in self.complex_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="COMPLEX", confidence=0.7, model=self.config.GEMINI_MODEL, estimated_cost="high")
                
        for kw in self.simple_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="SIMPLE", confidence=0.7, model="gemini/gemini-2.5-flash", estimated_cost="low")
                
        # Default to COMPLEX if unsure
        return TriageResult(classification="COMPLEX", confidence=0.5, model=self.config.GEMINI_MODEL, estimated_cost="high")

def get_triage_router() -> TriageRouter:
    return TriageRouter()
