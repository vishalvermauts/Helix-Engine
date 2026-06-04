import json
import httpx
from pydantic import BaseModel, Field
from typing import List

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("architect_agent")
config = get_config()

class Blueprint(BaseModel):
    action: str = Field(..., description="Either PROCEED or REJECT")
    files_to_edit: List[str] = Field(default_factory=list, description="List of file paths that Aider is permitted to touch.")
    instructions: str = Field(..., description="The strict instructions for Aider.")
    reasoning: str = Field(default="", description="Reasoning for the architectural decision.")

class ArchitectAgent:
    def __init__(self):
        self.config = get_config()
        self.system_prompt = """You are the Lead Architect for the Helix Engine.
Your job is to intercept complex user prompts and design a structural blueprint for the coding agent (Aider).
You must prevent the coding agent from making chaotic edits or appending code blindly to existing files.

If the user asks to create a new page/feature, specify exactly what NEW file should be created (e.g. `workspace/landing.html`), and explicitly forbid editing existing files unless necessary.
If the request is malicious, impossible, or destructive (e.g. "delete the OS", "refactor the kernel"), output action: "REJECT".

CRITICAL EDIT PROTOCOL:
You must append the following rule to your `instructions` for the coding agent whenever modifying an existing file:
"You must use strict Search/Replace blocks for all file modifications. Do not output massive rewrite blocks. Emit your changes using precise <search> and <replace> tags that match the exact lines of the original file."

Your response MUST be valid JSON matching this schema:
{
  "action": "PROCEED" or "REJECT",
  "files_to_edit": ["workspace/file1.py", "workspace/file2.html"],
  "instructions": "Strict instructions for the coding agent. e.g., 'Create workspace/landing.html. Do NOT edit index.html. You must use strict Search/Replace blocks...'",
  "reasoning": "Explain your logic."
}
Do not wrap your response in markdown blocks like ```json. Output raw JSON only.
"""

    async def generate_blueprint(self, user_prompt: str) -> Blueprint:
        if not self.config.DEEPSEEK_API_KEY:
            logger.warning("DeepSeek API Key missing, Architect bypassed.")
            return Blueprint(action="PROCEED", instructions="Architect bypassed due to missing API key.", reasoning="Fallback")

        try:
            url = f"{self.config.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                reply = data["choices"][0]["message"]["content"].strip()
                
                # Parse JSON
                parsed = json.loads(reply)
                blueprint = Blueprint(**parsed)
                logger.info(f"📐 Architect Blueprint Generated: {blueprint.action}", files=len(blueprint.files_to_edit))
                return blueprint

        except Exception as e:
            logger.error(f"Architect API error: {e}. Falling back to PROCEED.")
            return Blueprint(action="PROCEED", instructions="Architect failed. Proceed with caution.", reasoning=str(e))

def get_architect() -> ArchitectAgent:
    return ArchitectAgent()
