# =============================================================================
# DEPRECATED — manager_agent.py
# =============================================================================
# Status  : ARCHIVED — not imported by any active code path
# Replaced: agents/orchestrator.py  (swarm execution)
#           agents/planner_agent.py (blueprint generation)
#           agents/triage_router.py (model routing)
#
# Preserved because:
#   - capture_screenshot() + analyze_vision_feedback() contain a Gemini
#     multimodal vision loop that may be revived as a visual QA skill.
#   - run_aider_cycle() shows the original sync aider integration pattern.
#
# DO NOT import this module from server.py or any active agent.
# =============================================================================

import os
import base64
import subprocess
from pathlib import Path
import httpx

WORKSPACE_DIR = Path("./workspace").resolve()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

class OrchestratorAgent:
    def __init__(self, deepseek_key: str, gemini_key: str):
        self.gemini_key = gemini_key
        # Ensure your shell environments carry the auth credentials for Aider's internal process calls
        if deepseek_key:
            os.environ["DEEPSEEK_API_KEY"] = deepseek_key

    def run_aider_cycle(self, instructions: str) -> str:
        """Invokes Aider CLI headlessly to alter target repository structures safely."""
        print(f"[AirCode System] Launching Aider sub-process thread with prompt: {instructions}")
        
        # We target workspace/index.html explicitly using the robust shell wrapper
        command = [
            "aider",
            "--model", "deepseek/deepseek-chat",
            "--yes-always",
            "--message", instructions,
            str(WORKSPACE_DIR / "index.html")
        ]
        
        # Execute shell call, capturing outputs without locking the primary loop thread
        # In Windows, setting shell=True might be needed for 'aider', but let's stick to subprocess standard
        result = subprocess.run(command, capture_output=True, text=True, shell=os.name == 'nt')
        print(result.stdout)
        if result.stderr:
            print("[AirCode System Error]:", result.stderr)
            
        # Validate the workspace code against contracts
        from lib.contract_validator import ContractValidator
        validator = ContractValidator(str(WORKSPACE_DIR))
        is_valid, msg = validator.validate_workspace()
        
        if not is_valid:
            print(f"[AirCode System] AST Validation Failed: {msg}")
            # Trigger automatic correction cycle
            return f"CRITICAL VALIDATION ERROR: {msg}. Please immediately fix the code to match the active_blueprint.json contract."
            
        return "Workspace modifications written and validated successfully."

    def capture_screenshot(self) -> str:
        """Triggers Playwright CLI headlessly to snapshot visual layout canvases."""
        output_path = WORKSPACE_DIR / "current_output.png"
        target_file = WORKSPACE_DIR / "index.html"
        
        print(f"[AirCode System] Snapshotting rendered layout of {target_file}")
        
        # npx playwright screenshot with headless constraints to prevent cloud-container crashes
        # For Windows compatibility, using subprocess instead of os.system
        command = f"npx playwright screenshot --headless \"file:///{target_file.as_posix()}\" \"{output_path.as_posix()}\""
        subprocess.run(command, shell=True)
        return str(output_path)

    def analyze_vision_feedback(self, target_img_bytes: bytes, current_img_path: str) -> str:
        """Pipes reference assets alongside local snapshots to Gemini for structural audits."""
        print("[AirCode System] Constructing multi-modal layout payload...")
        
        with open(current_img_path, "rb") as f:
            current_bytes = f.read()

        # Structural Google AI Studio multi-modal API payload
        payload = {
            "contents": [{
                "parts": [
                    {"text": (
                        "Analyze these two frontend designs. Image 1 is the objective user layout mock. "
                        "Image 2 is what my automated layout assistant built inside the active folder. "
                        "Identify structural errors, bad column wraps, alignment padding bugs, or text scaling issues. "
                        "Provide crisp, direct, step-by-step instructions telling the coding engine exactly how to change "
                        "the HTML/CSS to fix the issues. "
                        "If the design matches perfectly, respond explicitly with the phrase: 'Layout match criteria achieved'."
                    )},
                    {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(target_img_bytes).decode("utf-8")}},
                    {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(current_bytes).decode("utf-8")}}
                ]
            }]
        }

        headers = {"Content-Type": "application/json"}
        response = httpx.post(f"{GEMINI_URL}?key={self.gemini_key}", json=payload, headers=headers, timeout=45.0)
        
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"[AirCode System] Failed to extract JSON properties from Gemini vision callback: {e}")
            return "Verify general container margins and evaluate font weights."
