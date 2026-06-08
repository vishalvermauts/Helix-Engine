import json
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger("episodic_memory")

class EpisodicMemory:
    def __init__(self, memory_file: str = "guardrails.json"):
        # The memory file is stored in the same directory as this script by default
        self.memory_path = Path(__file__).parent / memory_file
        self._ensure_memory_file_exists()

    def _ensure_memory_file_exists(self):
        if not self.memory_path.exists():
            default_data = {
                "guardrails": [
                    {
                        "keywords": ["all"],
                        "rule": "Always follow security best practices and do not hardcode secrets."
                    }
                ]
            }
            with open(self.memory_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=4)

    def load_guardrails(self) -> List[Dict[str, Any]]:
        try:
            with open(self.memory_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("guardrails", [])
        except Exception as e:
            logger.error(f"Failed to load episodic memory: {e}")
            return []

    def get_relevant_guardrails(self, prompt: str) -> List[str]:
        """
        Retrieves guardrails relevant to the prompt.
        Uses basic keyword matching for now.
        """
        prompt_lower = prompt.lower()
        guardrails = self.load_guardrails()
        relevant_rules = []

        for item in guardrails:
            keywords = item.get("keywords", [])
            rule = item.get("rule", "")
            
            # "all" keyword means it applies to every prompt
            if "all" in keywords:
                relevant_rules.append(rule)
                continue
            
            for kw in keywords:
                if kw.lower() in prompt_lower:
                    relevant_rules.append(rule)
                    break
                    
        return relevant_rules
        
    def add_guardrail(self, keywords: List[str], rule: str):
        """
        Adds a new guardrail to the episodic memory.
        """
        guardrails = self.load_guardrails()
        guardrails.append({"keywords": keywords, "rule": rule})
        
        try:
            with open(self.memory_path, 'w', encoding='utf-8') as f:
                json.dump({"guardrails": guardrails}, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save guardrail to episodic memory: {e}")

_episodic_memory_instance = None

def get_episodic_memory() -> EpisodicMemory:
    global _episodic_memory_instance
    if _episodic_memory_instance is None:
        _episodic_memory_instance = EpisodicMemory()
    return _episodic_memory_instance
