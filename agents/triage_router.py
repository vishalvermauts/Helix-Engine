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
    classification: str = Field(..., description="Either SIMPLE, COMPLEX, AGENT_GENERATION, or QA_TESTING")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    model: str = Field(..., description="The LLM model to be used based on classification")
    estimated_cost: str = Field(default="unknown")
    matched_skills: List[str] = Field(default_factory=list, description="Absolute paths to matched YAML skill files")

class TriageRouter:
    def __init__(self):
        self.config = get_config()
        self.simple_keywords = ["typo", "readme", "comment", "lint", "format", "rename"]
        self.complex_keywords = ["scaffold", "database", "refactor", "architecture", "design", "async", "web"]
        self.agent_keywords = ["agent", "bot", "auto-design", "script"]
        self.qa_keywords = ["test", "qa", "ci", "pipeline", "pytest"]
        self.skills_dir = Path(self.config.WORKSPACE_DIR) / "core_memory" / "skills"

    def scan_for_skills(self, prompt: str) -> List[str]:
        """Scans the dynamic YAML skills module and returns paths of matching skills."""
        matched = []
        if not self.skills_dir.exists():
            return matched
            
        prompt_lower = prompt.lower()
        
        keyword_pattern = re.compile(r'trigger_keywords:\s*\[(.*?)\]')
        
        for skill_file in self.skills_dir.glob("*.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                match = keyword_pattern.search(content)
                if match:
                    raw_keywords = match.group(1)
                    keywords = [k.strip().strip('\'"') for k in raw_keywords.split(",")]
                    
                    for kw in keywords:
                        if kw and kw.lower() in prompt_lower:
                            matched.append(str(skill_file.absolute()))
                            logger.info(f"Skill match found: {skill_file.name} (triggered by '{kw}')")
                            break
            except Exception as e:
                logger.error(f"Error reading skill file {skill_file}: {e}")
                
        return matched

    async def classify_prompt(self, prompt: str) -> TriageResult:
        matched_skills = self.scan_for_skills(prompt)

        if "[FORCE_SIMPLE]" in prompt:
            logger.info("Manual override detected: [FORCE_SIMPLE]")
            return TriageResult(classification="SIMPLE", confidence=1.0, model="gemini/gemini-2.5-flash", estimated_cost="low", matched_skills=matched_skills)
        if "[FORCE_COMPLEX]" in prompt:
            logger.info("Manual override detected: [FORCE_COMPLEX]")
            return TriageResult(classification="COMPLEX", confidence=1.0, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)

        if not self.config.DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API Key missing, falling back to local heuristic.")
            return self._local_fallback(prompt, matched_skills)

        try:
            url = f"{self.config.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "You are a routing agent. Reply with exactly one word: "
                "'SIMPLE' if the user request is a minor formatting, typo, or comment change. "
                "'AGENT_GENERATION' if the user wants to create a python agent, bot, or automated script. "
                "'QA_TESTING' if the user wants to write unit tests, QA suites, or CI pipelines. "
                "'COMPLEX' if it involves architecture, scaffolding, logic changes, or refactoring general applications."
            )
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
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
                
                if "AGENT_GENERATION" in reply:
                    return TriageResult(classification="AGENT_GENERATION", confidence=0.9, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                elif "QA_TESTING" in reply:
                    return TriageResult(classification="QA_TESTING", confidence=0.9, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                elif "SIMPLE" in reply:
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
        prompt_lower = prompt.lower()
        
        for kw in self.agent_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="AGENT_GENERATION", confidence=0.7, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.qa_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="QA_TESTING", confidence=0.7, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.complex_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="COMPLEX", confidence=0.7, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.simple_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="SIMPLE", confidence=0.7, model="gemini/gemini-2.5-flash", estimated_cost="low", matched_skills=matched_skills)
                
        return TriageResult(classification="COMPLEX", confidence=0.5, model=self.config.GEMINI_MODEL, estimated_cost="high", matched_skills=matched_skills)

def get_triage_router() -> TriageRouter:
    return TriageRouter()
