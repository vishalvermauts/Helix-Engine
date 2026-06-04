import re
import httpx
from typing import Optional, List
from pathlib import Path
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
    matched_skills: List[str] = Field(default_factory=list, description="Absolute paths to matched YAML skill files")

class TriageRouter:
    def __init__(self):
        self.config = get_config()
        self.simple_keywords = ["typo", "readme", "comment", "lint", "format", "rename"]
        self.complex_keywords = ["scaffold", "database", "refactor", "architecture", "design", "async"]
        self.skills_dir = Path(self.config.WORKSPACE_DIR) / "core_memory" / "skills"

    def scan_for_skills(self, prompt: str) -> List[str]:
        """Scans the dynamic YAML skills module and returns paths of matching skills."""
        matched = []
        if not self.skills_dir.exists():
            return matched
            
        prompt_lower = prompt.lower()
        
        # Regex to capture the JSON-like array in YAML front-matter
        # e.g. trigger_keywords: ["html", "css", "layout"]
        keyword_pattern = re.compile(r'trigger_keywords:\s*\[(.*?)\]')
        
        for skill_file in self.skills_dir.glob("*.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                match = keyword_pattern.search(content)
                if match:
                    raw_keywords = match.group(1)
                    # parse words by splitting on commas and stripping quotes
                    keywords = [k.strip().strip('\'"') for k in raw_keywords.split(",")]
                    
                    for kw in keywords:
                        if kw and kw.lower() in prompt_lower:
                            matched.append(str(skill_file.absolute()))
                            logger.info(f"Skill match found: {skill_file.name} (triggered by '{kw}')")
                            break # No need to match multiple keywords for the same file
            except Exception as e:
                logger.error(f"Error reading skill file {skill_file}: {e}")
                
        return matched

    async def classify_prompt(self, prompt: str) -> TriageResult:
        # Scan for skills first
        matched_skills = self.scan_for_skills(prompt)

        # 1. Manual Overrides
        if "[FORCE_SIMPLE]" in prompt:
            logger.info("Manual override detected: [FORCE_SIMPLE]")
            return TriageResult(classification="SIMPLE", confidence=1.0, model="gemini/gemini-2.5-flash", estimated_cost="low", matched_skills=matched_skills)
        if "[FORCE_COMPLEX]" in prompt:
            logger.info("Manual override detected: [FORCE_COMPLEX]")
            return TriageResult(classification="COMPLEX", confidence=1.0, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)

        # 2. DeepSeek V3 API Hook
        if not self.config.DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API Key missing, falling back to local heuristic.")
            return self._local_fallback(prompt, matched_skills)

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
                    return TriageResult(classification="SIMPLE", confidence=0.9, model="gemini/gemini-2.5-flash", estimated_cost="low", matched_skills=matched_skills)
                elif "COMPLEX" in reply:
                    return TriageResult(classification="COMPLEX", confidence=0.9, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                else:
                    logger.warning(f"Unexpected DeepSeek reply: {reply}")
                    return self._local_fallback(prompt, matched_skills)

        except httpx.TimeoutException:
            logger.warning("DeepSeek API timeout (1.5s exceeded). Using local fallback.")
            return self._local_fallback(prompt, matched_skills)
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}. Using local fallback.")
            return self._local_fallback(prompt, matched_skills)

    def _local_fallback(self, prompt: str, matched_skills: List[str]) -> TriageResult:
        """Local fast-path keyword scan fallback."""
        prompt_lower = prompt.lower()
        
        # Check complex first as it's safer to overestimate
        for kw in self.complex_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="COMPLEX", confidence=0.7, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.simple_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="SIMPLE", confidence=0.7, model="gemini/gemini-2.5-flash", estimated_cost="low", matched_skills=matched_skills)
                
        # Default to COMPLEX if unsure
        return TriageResult(classification="COMPLEX", confidence=0.5, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)

def get_triage_router() -> TriageRouter:
    return TriageRouter()
