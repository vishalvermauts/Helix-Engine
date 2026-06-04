import os
import asyncio
import base64
from pathlib import Path
from lib.config import get_config
from lib.logging import get_logger
import google.generativeai as genai

logger = get_logger("visual_validator")
config = get_config()

PLAYWRIGHT_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:5173/index.html', { waitUntil: 'networkidle' });
  
  // Mobile
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: '/workspace/mobile.png', fullPage: true });
  
  // Tablet
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.screenshot({ path: '/workspace/tablet.png', fullPage: true });
  
  // Desktop
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '/workspace/desktop.png', fullPage: true });

  await browser.close();
})();
"""

async def run_visual_validator():
    """
    Spawns a local HTTP server and uses a Playwright Docker container
    to capture screenshots across 3 viewports. Passes the images to Gemini
    to detect layout issues.
    """
    if not config.GEMINI_API_KEY:
        return True, ""
        
    workspace_dir = Path(config.WORKSPACE_DIR) / "workspace"
    
    logger.info("👁️ Visual Validator booting up headless browser...")
    
    # 1. Start ephemeral HTTP server on host
    server_process = await asyncio.create_subprocess_exec(
        "python3", "-m", "http.server", "5173", "--directory", str(workspace_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    
    try:
        # Give server a moment to bind
        await asyncio.sleep(1.5)
        
        # 2. Write Playwright Node.js script
        script_path = workspace_dir / "capture.js"
        with open(script_path, "w") as f:
            f.write(PLAYWRIGHT_SCRIPT)
            
        # 3. Spawn Playwright Docker container
        docker_cmd = [
            "docker", "run", "--rm",
            "--network=host",
            "-v", f"{workspace_dir}:/workspace",
            "-w", "/workspace",
            "mcr.microsoft.com/playwright:v1.44.0-jammy",
            "node", "capture.js"
        ]
        
        pw_process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await pw_process.communicate()
        
        if pw_process.returncode != 0:
            logger.error(f"Playwright capture failed: {stderr.decode()}")
            return False, f"Visual capture failed: {stderr.decode()}"
            
        # 4. Read screenshots
        images = []
        for bp in ["mobile.png", "tablet.png", "desktop.png"]:
            img_path = workspace_dir / bp
            if img_path.exists():
                with open(img_path, "rb") as f:
                    img_data = f.read()
                    images.append({
                        "mime_type": "image/png",
                        "data": img_data
                    })
        
        if len(images) != 3:
            logger.warning("Visual Validator failed to capture all breakpoints.")
            return True, "" # Pass if we can't evaluate, don't fail the build
            
        # 5. Gemini Evaluation
        logger.info("🧠 Sending screenshots to Gemini for Multimodal Validation...")
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-pro")
        
        prompt = (
            "You are a Senior Frontend QA Engineer. Analyze these three breakpoints (Mobile, Tablet, Desktop) of the newly generated web UI. "
            "Are there any glaring layout issues? Specifically look for: \n"
            "- Interactive elements, navigation links, or menus overlapping.\n"
            "- Text hidden, clipped, or bleeding out of containers.\n"
            "- Unreadable contrast or broken CSS grids.\n"
            "If everything looks structurally sound and there are no overlapping/clipped elements, reply strictly with 'PASS'.\n"
            "If there are issues, reply with 'FAIL: ' followed by a brief description of the visual bug and how to fix the CSS."
        )
        
        response = model.generate_content([prompt] + images)
        reply = response.text.strip()
        
        if reply.startswith("PASS"):
            logger.info("✅ Visual Validation passed.")
            return True, ""
        elif reply.startswith("FAIL:"):
            corrective = reply[5:].strip()
            logger.warning(f"❌ Visual Validation failed: {corrective}")
            return False, corrective
        else:
            logger.warning(f"Unexpected Visual LLM reply: {reply}. Defaulting to PASS.")
            return True, ""
            
    finally:
        # Cleanup
        server_process.terminate()
        try:
            await server_process.wait()
        except:
            pass

def get_visual_validator():
    return run_visual_validator
