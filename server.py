import os
import sys
import asyncio
import time
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
import httpx

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

app = FastAPI()
app.mount("/workspace", StaticFiles(directory="/workspaces/AirCode/workspace", html=True), name="workspace")

# 🔴 INJECT YOUR TRUE TELEGRAM PARAMETERS HERE
TOKEN = "8982235895:AAHG8emWnJLyryuS2xGjrYJWyuQZAjKr0cQ"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

pipeline_lock = asyncio.Lock()

async def send_telegram_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        try:
            await client.post(TELEGRAM_URL, json={"chat_id": chat_id, "text": text})
        except Exception as e:
            print(f"Telegram alert delivery failure: {e}")

async def processing_pipeline(chat_id: int, prompt: str):
    if pipeline_lock.locked():
        await send_telegram_message(chat_id, "⚠️ Pipeline is currently busy cooking another page. Please wait a moment!")
        return

    async with pipeline_lock:
        env = os.environ.copy()
        
        # 🔴 INJECT YOUR TRUE NATIVE GOOGLE API KEY HERE
        env["GEMINI_API_KEY"] = "AQ.Ab8RN6J5HEQArxZUC_7CMrcjH2uFIapg1yqgOiWqO8WXwDw-uA" 
        
        workspace_dir = "/workspaces/AirCode/workspace"
        os.makedirs(workspace_dir, exist_ok=True)

        await send_telegram_message(chat_id, "🚀 [AirCode] Google API Authenticated. Building your UI components...")
        
        aider_cmd = [
            "/home/vboxuser/.local/bin/aider",
            "--model", "gemini/gemini-2.5-pro",
            "--no-show-model-warnings",
            "--yes-always",
            "--no-suggest-shell-commands",
            "--no-gitignore",
            "--no-check-update",
            "--message", prompt
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *aider_cmd,
                cwd=workspace_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            print(f"Aider Output: {stdout.decode()}")
            print(f"Aider Errors: {stderr.decode()}")
            
            if "APIKeyNotValid" in stdout.decode() or "APIKeyNotValid" in stderr.decode() or "401" in stderr.decode():
                await send_telegram_message(chat_id, "❌ Native Google API Key authentication failed. Double check your AI Studio key token string!")
            else:
                await send_telegram_message(chat_id, "✨ [AirCode Complete] Page updated successfully inside your workspace!")
        except Exception as loop_err:
            print(f"Pipeline error: {loop_err}")
            await send_telegram_message(chat_id, "❌ Critical system error inside the processing thread pipeline.")

@app.get("/")
async def root_check():
    return {"status": "online", "engine": "AirCode Layer"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        if "message" not in data:
            return Response(status_code=200)
            
        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()
        
        if not text:
            return Response(status_code=200)

        if text.lower() == "/start":
            current_time = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            health_card = (
                "Hello Vishal! AirCode Engine is active.\n\n"
                " Status: Healthy\n"
                " Pipeline: Ready (Native Google AI)\n"
                f" Checked: {current_time}\n\n"
                "Send me a single page instruction to build your UI portfolio!"
            )
            await send_telegram_message(chat_id, health_card)
            return Response(status_code=200)

        asyncio.create_task(processing_pipeline(chat_id, text))
        
    except Exception as e:
        print(f"Webhook exception: {e}")
        
    return Response(status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
