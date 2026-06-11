import re
import httpx
import random
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("triage_router")
config = get_config()


@dataclass
class TriageStats:
    """In-memory accumulator for triage routing metrics."""
    session_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_classified: int = 0
    counts: Dict[str, int] = field(default_factory=lambda: {
        "SIMPLE": 0,
        "COMPLEX": 0,
        "AGENT_GENERATION": 0,
        "QA_TESTING": 0,
    })
    # Cumulative estimated costs in USD
    total_cost_low: float = 0.0   # DeepSeek/Flash (SIMPLE)
    total_cost_high: float = 0.0  # Gemini Pro (COMPLEX, AGENT_GENERATION, QA_TESTING)
    # Cost constants
    COST_SIMPLE: float = 0.0001
    COST_COMPLEX: float = 0.005
    # Phase 5: canary bypass counter
    canary_bypassed: int = 0
    # Phase 6: peak simple throughput high-watermark (simples/hour)
    peak_simple_per_hour: float = 0.0

    def record(self, classification: str, estimated_cost: str) -> None:
        self.total_classified += 1
        self.counts[classification] = self.counts.get(classification, 0) + 1
        if estimated_cost == "low":
            self.total_cost_low += self.COST_SIMPLE
        else:
            self.total_cost_high += self.COST_COMPLEX
        # Update rolling peak: simples in the current hour window
        now = datetime.now(timezone.utc)
        elapsed_h = max(1, (now - self.session_start).total_seconds() / 3600)
        current_rate = self.counts.get("SIMPLE", 0) / elapsed_h
        if current_rate > self.peak_simple_per_hour:
            self.peak_simple_per_hour = current_rate

    def savings_vs_all_complex(self) -> float:
        """How much cheaper the actual routing was vs always using Gemini Pro."""
        baseline = self.total_classified * self.COST_COMPLEX
        actual = self.total_cost_low + self.total_cost_high
        return max(0.0, baseline - actual)

    def uptime_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self.session_start).total_seconds())

    def summary_dict(self) -> dict:
        return {
            "session_start": self.session_start.isoformat(),
            "uptime_seconds": self.uptime_seconds(),
            "total_classified": self.total_classified,
            "canary_bypassed": self.canary_bypassed,
            "counts": dict(self.counts),
            "total_cost_usd": round(self.total_cost_low + self.total_cost_high, 6),
            "estimated_savings_usd": round(self.savings_vs_all_complex(), 6),
            "simple_ratio_pct": round(
                100 * self.counts.get("SIMPLE", 0) / max(1, self.total_classified), 1
            ),
            "peak_simple_per_hour": self.peak_simple_per_hour,
        }


# Singleton stats tracker
_triage_stats: TriageStats = TriageStats()


def get_triage_stats() -> TriageStats:
    return _triage_stats

class TriageResult(BaseModel):
    classification: str = Field(..., description="Either SIMPLE, COMPLEX, AGENT_GENERATION, or QA_TESTING")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    model: str = Field(..., description="The LLM model to be used based on classification")
    estimated_cost: str = Field(default="unknown")
    matched_skills: List[str] = Field(default_factory=list, description="Absolute paths to matched YAML skill files")

class TriageRouter:
    def __init__(self):
        self.config = get_config()
        # Phase 6: expanded keyword sets from real aider usage patterns
        self.simple_keywords = [
            # typo & doc
            "typo", "typos", "readme", "comment", "comments", "docstring",
            # formatting
            "lint", "format", "formatting", "whitespace", "indent",
            # minor edits
            "rename", "fix", "bug", "bugfix", "patch", "hotfix",
            "correct", "update", "tweak", "adjust", "spelling",
            # single-file add
            "add a line", "add comment", "print", "log",
        ]
        self.complex_keywords = [
            # architecture
            "scaffold", "architecture", "redesign", "restructure", "overhaul",
            # database
            "database", "schema", "migration", "migrate", "orm",
            # refactoring
            "refactor", "refactoring", "extract", "modularize",
            # multi-file / full features
            "multi-file", "async", "concurrency", "threading",
            # UI / web
            "web", "frontend", "ui", "ux", "dashboard", "layout",
            "react", "vue", "svelte", "html", "css",
            # integrations
            "oauth", "authentication", "auth", "jwt", "api", "graphql",
            "websocket", "microservice",
        ]
        self.agent_keywords = [
            "agent", "bot", "auto-design", "autonomous", "automation",
            "script", "daemon", "workflow", "pipeline", "orchestrate",
        ]
        self.qa_keywords = [
            "test", "tests", "qa", "ci", "cd", "pytest", "unittest",
            "coverage", "mock", "assert", "fixture", "integration test",
            "end-to-end", "e2e",
        ]
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

    async def classify_prompt(self, prompt: str) -> TriageResult:  # noqa: C901
        matched_skills = self.scan_for_skills(prompt)

        # ── Phase 5: Canary gate ─────────────────────────────────────────────
        # If TRIAGE_CANARY_RATE < 1.0, only route that fraction of traffic
        # through the full triage pipeline. The rest falls back immediately to
        # the configured fallback model so we can A/B compare cost & quality.
        canary_rate = getattr(self.config, "TRIAGE_CANARY_RATE", 1.0)
        if canary_rate < 1.0 and random.random() > canary_rate:
            _triage_stats.canary_bypassed += 1
            fallback_model = getattr(self.config, "TRIAGE_FALLBACK_MODEL", self.config.GEMINI_MODEL)
            logger.debug(
                "Canary bypass: routing outside triage",
                canary_rate=canary_rate,
                model=fallback_model,
            )
            return TriageResult(
                classification="COMPLEX",
                confidence=0.5,
                model=fallback_model,
                estimated_cost="high",
                matched_skills=matched_skills,
            )
        # ────────────────────────────────────────────────────────────────────

        if "[FORCE_SIMPLE]" in prompt:
            logger.info("Manual override detected: [FORCE_SIMPLE]")
            result = TriageResult(classification="SIMPLE", confidence=1.0, model=self._select_model("SIMPLE"), estimated_cost="low", matched_skills=matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result
        if "[FORCE_AGENT]" in prompt or "[FORCE_AGENT_GENERATION]" in prompt:
            logger.info("Manual override detected: [FORCE_AGENT_GENERATION]")
            result = TriageResult(classification="AGENT_GENERATION", confidence=1.0, model=self._select_model("AGENT_GENERATION"), estimated_cost="high", matched_skills=matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result
        if "[FORCE_COMPLEX]" in prompt:
            logger.info("Manual override detected: [FORCE_COMPLEX]")
            result = TriageResult(classification="COMPLEX", confidence=1.0, model=self._select_model("COMPLEX"), estimated_cost="high", matched_skills=matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result

        if not self.config.DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API Key missing, falling back to local heuristic.")
            result = self._local_fallback(prompt, matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result

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
                "'COMPLEX' if it involves building web UIs, frontends, HTML/CSS/JS pages, dashboards, or complex app scaffolding, architecture, and logic changes."
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
                    result = TriageResult(classification="AGENT_GENERATION", confidence=0.9, model=self._select_model("AGENT_GENERATION"), estimated_cost="high", matched_skills=matched_skills)
                elif "QA_TESTING" in reply:
                    result = TriageResult(classification="QA_TESTING", confidence=0.9, model=self._select_model("QA_TESTING"), estimated_cost="high", matched_skills=matched_skills)
                elif "SIMPLE" in reply:
                    result = TriageResult(classification="SIMPLE", confidence=0.9, model=self._select_model("SIMPLE"), estimated_cost="low", matched_skills=matched_skills)
                elif "COMPLEX" in reply:
                    result = TriageResult(classification="COMPLEX", confidence=0.9, model=self._select_model("COMPLEX"), estimated_cost="high", matched_skills=matched_skills)
                else:
                    logger.warning(f"Unexpected DeepSeek reply: {reply}")
                    result = self._local_fallback(prompt, matched_skills)
                
                _triage_stats.record(result.classification, result.estimated_cost)
                return result

        except httpx.TimeoutException:
            logger.warning("DeepSeek API timeout (1.5s exceeded). Using local fallback.")
            result = self._local_fallback(prompt, matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}. Using local fallback.")
            result = self._local_fallback(prompt, matched_skills)
            _triage_stats.record(result.classification, result.estimated_cost)
            return result

    def _select_model(self, classification: str) -> str:
        """
        Phase 6: Central model-selection helper.

        Routing table:
          SIMPLE           → gemini/gemini-2.5-flash  (cheap, fast)
          AGENT_GENERATION → Claude Haiku (if key set), else Gemini Pro
          QA_TESTING       → Claude Haiku (if key set), else Gemini Pro
          COMPLEX          → Gemini Pro (default heavyweight model)
        """
        claude_key = getattr(self.config, "CLAUDE_API_KEY", "")
        claude_model = getattr(self.config, "CLAUDE_MODEL", "claude-3-5-haiku-20241022")

        if self.config.VERTEX_ENABLED:
            if classification == "SIMPLE":
                return "vertex_ai/gemini-2.5-flash"
            elif classification in ("AGENT_GENERATION", "QA_TESTING") and claude_key:
                return f"anthropic/{claude_model}"
            else:
                model = self.config.GEMINI_MODEL
                if not model.startswith("vertex_ai/"):
                    if "/" in model:
                        model = "vertex_ai/" + model.split("/")[-1]
                    else:
                        model = "vertex_ai/" + model
                return model
        else:
            if classification == "SIMPLE":
                return "gemini/gemini-2.5-flash"
            elif classification in ("AGENT_GENERATION", "QA_TESTING") and claude_key:
                return f"anthropic/{claude_model}"
            else:
                return self.config.GEMINI_MODEL

    def _local_fallback(self, prompt: str, matched_skills: List[str]) -> TriageResult:
        """Keyword-only classification used when DeepSeek is unavailable."""
        prompt_lower = prompt.lower()
        
        for kw in self.agent_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="AGENT_GENERATION", confidence=0.7, model=self._select_model("AGENT_GENERATION"), estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.qa_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="QA_TESTING", confidence=0.7, model=self._select_model("QA_TESTING"), estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.complex_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="COMPLEX", confidence=0.7, model=self._select_model("COMPLEX"), estimated_cost="high", matched_skills=matched_skills)
                
        for kw in self.simple_keywords:
            if kw in prompt_lower:
                return TriageResult(classification="SIMPLE", confidence=0.7, model=self._select_model("SIMPLE"), estimated_cost="low", matched_skills=matched_skills)
                
        return TriageResult(classification="COMPLEX", confidence=0.5, model=self._select_model("COMPLEX"), estimated_cost="high", matched_skills=matched_skills)

def get_triage_router() -> TriageRouter:
    return TriageRouter()
