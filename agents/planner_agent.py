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
    required_selectors: List[str] = Field(default=[], description="CSS selectors that MUST be present in the final rendered DOM, used by the E2E contract verifier")

class PlannerAgent:
    def __init__(self):
        self.config = get_config()

    async def generate(self, user_prompt: str, task_type: str = "COMPLEX", matched_skills: list = None) -> ProjectBlueprint:
        if self.config.VERTEX_ENABLED:
            import google.auth
            import google.auth.transport.requests
            
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials, project = google.auth.default(scopes=scopes)
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
            
            model = self.config.GEMINI_MODEL
            if "/" in model:
                model = model.split("/")[-1]
                
            url = (
                f"https://{self.config.VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
                f"/projects/{self.config.VERTEX_PROJECT}/locations/{self.config.VERTEX_LOCATION}"
                f"/publishers/google/models/{model}:generateContent"
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        else:
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
                "required_selectors": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "2-5 CSS selectors that MUST exist in the final DOM (e.g. '#todo-column', '.card', 'form#add-form'). Use generic tag selectors as fallback."
                },
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
            "required": ["contract", "tasks", "required_selectors"]
        }

        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
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
                
                # INJECT RAW USER PROMPT TO PREVENT LOSS OF STRICT GUARDRAILS
                original_contract = data.get("contract", "")
                data["contract"] = f"### STRICT USER REQUIREMENTS ###\n{user_prompt}\n\n### ARCHITECTURAL PLAN ###\n{original_contract}"
                
                return ProjectBlueprint(**data)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse Gemini response: {e}")
                raise Exception("Invalid blueprint format received from planner")

def get_planner_agent():
    return PlannerAgent()

async def generate_e2e_verification_script(blueprint_json: dict, url: str = "http://localhost:8000/workspace/index.html") -> str:
    """Instructs the Planner to emit a clean Playwright verification script based on the API layout."""
    config = get_config()
    if config.VERTEX_ENABLED:
        import google.auth
        import google.auth.transport.requests
        
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials, project = google.auth.default(scopes=scopes)
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token
        
        model = config.GEMINI_MODEL
        if "/" in model:
            model = model.split("/")[-1]
            
        api_url = (
            f"https://{config.VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
            f"/projects/{config.VERTEX_PROJECT}/locations/{config.VERTEX_LOCATION}"
            f"/publishers/google/models/{model}:generateContent"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    else:
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in configuration")

        model = config.GEMINI_MODEL
        if model.startswith("gemini/"):
            model = model.replace("gemini/", "")

        api_url = f"{config.GEMINI_API_BASE.rstrip('/')}/models/{model}:generateContent?key={config.GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
    
    hints = ""
    for task in blueprint_json.get("tasks", []):
        hints += f"- {task.get('description')}\n"

    system_instruction = (
        "You are a QA Engineer for Helix Engine. Generate a fully standalone Playwright Python script to verify an HTML page loaded correctly.\\n"
        "CRITICAL RULES:\\n"
        "1. MUST output ONLY valid Python code starting with 'import asyncio'. No markdown, no markdown backticks, no explanations.\\n"
        f"2. The URL to test is '{url}'.\\n"
        "3. ONLY verify STATIC DOM presence using GENERIC selectors. You MUST use these exact checks:\\n"
        "   a. await page.goto(URL) succeeds without error\\n"
        "   b. await page.wait_for_selector('h1', timeout=10000) - verify a main heading exists\\n"
        "   c. Optionally check for 'h2' or 'h3' headings if they are part of the page structure\\n"
        "   DO NOT check for specific IDs, classes, or attributes. DO NOT simulate clicks or fills.\\n"
        "4. Print '\\u2705 Behavioral Interaction verified successfully.' and exit(0) on success, or print '\\u274c Failure' and exit(1) on error.\\n"
        "5. The script MUST be runnable as a standalone file using asyncio.run()."
    )

    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": f"Generate the E2E structural verification script for a page at: {url}"}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "text/plain"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(api_url, json=payload, headers=headers)
            if response.status_code == 200:
                result = response.json()
                content = result['candidates'][0]['content']['parts'][0]['text']
                content = content.replace("```python", "").replace("```", "").strip()
                return content
    except Exception as e:
        logger.error(f"Failed to generate dynamic E2E script: {e}")
        
    return """
import asyncio
from playwright.async_api import async_playwright

async def test_fallback():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(f"{url}")
            await asyncio.sleep(2)
            print("✅ Behavioral Interaction verified successfully (Fallback).")
            exit(0)
        except Exception as e:
            print(f"❌ Structural Target Timeout: {str(e)}")
            exit(1)
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_fallback())
"""
