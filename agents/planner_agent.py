import json
import httpx
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("planner_agent")

class GeneratedFile(BaseModel):
    path: str = Field(..., description="The relative path to the file")
    content: str = Field(..., description="The actual full, production-ready source code content for this file")

class WorkerTask(BaseModel):
    task_id: str = Field(..., description="A unique identifier for this task")
    description: str = Field(..., description="Detailed instructions for the worker agent to execute")
    target_files: List[str] = Field(..., description="List of files this worker is expected to create or modify")
    generated_files: List[GeneratedFile] = Field(default=[], description="The actual full source code contents for each file")
    depends_on: List[str] = Field(default=[], description="List of task_ids that must complete before this task can start")

class ProjectBlueprint(BaseModel):
    contract: str = Field(..., description="The comprehensive project contract, including styling rules, color palettes, and component structure")
    tasks: List[WorkerTask] = Field(..., description="The chunked worker tasks that form the DAG")

class PlannerAgent:
    def __init__(self):
        self.config = get_config()

    async def generate(self, user_prompt: str, task_type: str = "COMPLEX", matched_skills: list = None) -> ProjectBlueprint:
        if not self.config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in configuration")

        model = self.config.GEMINI_MODEL
        if model.startswith("gemini/"):
            model = model.replace("gemini/", "")

        url = f"{self.config.GEMINI_API_BASE.rstrip('/')}/models/{model}:generateContent?key={self.config.GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}

        system_instruction = "You are the Phase 6 Planner Agent for the AirCode Swarm Orchestrator. "
        if task_type == "AGENT_GENERATION":
            system_instruction += (
                "CRITICAL RULES: "
                "1. You are generating a Python script or AI agent. "
                "2. MUST output files inside a 'custom_agents/' directory (e.g. 'custom_agents/my_agent.py') to prevent overwriting core files. "
                "3. ENFORCE STRICT ERROR HANDLING: Never swallow generic 'Exception' blocks. Catch specific exceptions. "
                "4. PREFER NATIVE PYTHON LIBRARIES: Avoid using brittle 'subprocess.run' shell commands unless absolutely required. Use native python tools where possible. "
                "5. Ensure the code is production-ready Python 3 with comprehensive docstrings. "
                "6. Break the implementation into a sequence of tasks. Each task MUST include the full source code for every file it targets in 'generated_files'."
            )
        elif task_type == "QA_TESTING":
            system_instruction += (
                "CRITICAL RULES: "
                "1. You are generating a continuous integration / QA test suite. "
                "2. Generate target Python code and also write pytest files inside a 'tests/' directory. "
                "3. Provide realistic logic with intentional edge cases, and tests that comprehensively cover them. "
                "4. Break the implementation into a sequence of tasks. Each task MUST include the full source code for every file it targets in 'generated_files'."
            )
        else:
            system_instruction += (
                "CRITICAL RULES (VIOLATION CAUSES FATAL CRASH): "
                "1. MUST generate ONLY a flat static web application. No subdirectories. No 'public/', no 'src/'. "
                "2. HTML path MUST be exactly 'index.html'. "
                "3. CSS path MUST be exactly 'style.css'. JavaScript MUST be exactly 'script.js'. "
                "4. Link CSS strictly as <link rel='stylesheet' href='./style.css'>. NO absolute paths. "
                "5. ALWAYS inject <script src='https://cdn.tailwindcss.com'></script> in the <head> of index.html. "
                "6. DO NOT output package.json, webpack, tailwind.config.js, or ANY build files. "
                "7. Break the implementation into a sequence of tasks. Each task MUST include the full source code for every file it targets in 'generated_files'."
            )
            
        if matched_skills and len(matched_skills) > 0:
            system_instruction += "\n\n### RELEVANT SKILL CONTEXT:\n"
            for skill_path in matched_skills:
                try:
                    with open(skill_path, 'r', encoding='utf-8') as f:
                        skill_content = f.read()
                        system_instruction += f"\n--- SKILL FILE: {Path(skill_path).name} ---\n{skill_content}\n"
                except Exception as e:
                    logger.warning(f"Failed to load skill file {skill_path}: {e}")
        
        sandbox_influence = os.environ.get("HELIX_SYSTEM_PROMPT_APPEND")
        if sandbox_influence:
            system_instruction += f"\n\nCRITICAL DIRECTIVE (SANDBOX INFLUENCER): {sandbox_influence}"

        schema = {
            "type": "OBJECT",
            "properties": {
                "contract": {"type": "STRING"},
                "tasks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "task_id": {"type": "STRING"},
                            "description": {"type": "STRING"},
                            "target_files": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"}
                            },
                            "generated_files": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "path": {"type": "STRING"},
                                        "content": {"type": "STRING"}
                                    },
                                    "required": ["path", "content"]
                                }
                            },
                            "depends_on": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"}
                            }
                        },
                        "required": ["task_id", "description", "target_files", "generated_files"]
                    }
                }
            },
            "required": ["contract", "tasks"]
        }

        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": schema
            }
        }
        
        # Test hook: Load Mock LLM Payload
        mock_payload_file = os.environ.get("HELIX_MOCK_LLM_PAYLOAD")
        if mock_payload_file and Path(mock_payload_file).exists():
            logger.info(f"Using mock LLM payload from {mock_payload_file}")
            content_text = Path(mock_payload_file).read_text()
            data = json.loads(content_text)
            return ProjectBlueprint(**data)

        async with httpx.AsyncClient(timeout=300.0) as client:
            logger.info(f"Generating Phase 6 Blueprint using {model}...")
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Gemini API Error: {response.status_code} {response.text}")
                raise Exception(f"Gemini API Error: {response.text}")
                
            result = response.json()
            try:
                content_text = result['candidates'][0]['content']['parts'][0]['text']
                
                # Test hook: Save Mock LLM Payload
                save_payload_file = os.environ.get("HELIX_MOCK_LLM_PAYLOAD_SAVE")
                if save_payload_file:
                    Path(save_payload_file).write_text(content_text)
                    
                data = json.loads(content_text)
                return ProjectBlueprint(**data)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse Gemini response: {e}")
                raise Exception("Invalid blueprint format received from planner")

def get_planner_agent():
    return PlannerAgent()
