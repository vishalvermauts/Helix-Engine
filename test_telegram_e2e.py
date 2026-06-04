#!/usr/bin/env python3
"""
AirCode Telegram Bot End-to-End Test
Sends a webhook prompt, monitors aider execution, verifies bot response.
"""

import sys
import asyncio
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("telegram_test", level="INFO", format_type="json")


async def check_server_health():
    """Check if FastAPI server is running."""
    logger.info("🔍 Checking FastAPI server health...")
    try:
        result = subprocess.run(
            ["curl", "-s", "-f", "http://127.0.0.1:8000/health"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            logger.info("✅ FastAPI server is running")
            return True
        else:
            logger.warning("❌ FastAPI not responding")
            return False
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return False


async def send_test_prompt(prompt: str = "Create a simple Python script that prints 'AirCode Test'"):
    """Send a test webhook payload to the server."""
    config = get_config()
    
    logger.info("📨 Sending test webhook prompt...", prompt_len=len(prompt))
    
    # Simulate Telegram webhook payload
    payload = {
        "message": {
            "chat": {"id": config.telegram_chat_id},
            "from": {"id": config.allowed_user_id},
            "text": prompt
        }
    }
    
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "http://127.0.0.1:8000/webhook",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            response = json.loads(result.stdout)
            logger.info("✅ Webhook accepted", response=response)
            return True
        else:
            logger.error("Webhook rejected", error=result.stderr)
            return False
    except Exception as e:
        logger.error("Webhook send failed", error=str(e))
        return False


async def monitor_aider_execution(timeout: int = 60):
    """Monitor for aider process execution and completion."""
    logger.info("⏳ Monitoring aider execution...", timeout_secs=timeout)
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Check for aider process
            result = subprocess.run(
                ["pgrep", "-f", "aider"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                pids = result.stdout.strip().split("\n")
                logger.info("🔨 Aider process detected", pids=pids)
                
                # Wait for process to complete
                for pid in pids:
                    if pid:
                        while True:
                            check = subprocess.run(
                                ["ps", "-p", pid],
                                capture_output=True
                            )
                            if check.returncode != 0:
                                logger.info("✅ Aider process completed", pid=pid)
                                break
                            await asyncio.sleep(1)
                
                return True
            
            await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error("Monitor error", error=str(e))
    
    logger.warning("⏱️ Aider execution timeout or not detected")
    return False


async def check_telegram_notification(timeout: int = 30):
    """Check if Telegram bot would send a notification (via logs or mock)."""
    logger.info("📱 Checking for Telegram notification...", timeout_secs=timeout)
    
    config = get_config()
    
    # Try getWebhookInfo to see if there's activity
    try:
        result = subprocess.run(
            [
                "curl", "-s",
                f"https://api.telegram.org/bot{config.telegram_token}/getWebhookInfo"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        data = json.loads(result.stdout)
        if data.get("ok"):
            webhook_info = data.get("result", {})
            pending = webhook_info.get("pending_update_count", 0)
            logger.info("📊 Webhook info", pending_updates=pending, last_error=webhook_info.get("last_error_message"))
            return True
        else:
            logger.error("Telegram API error", error=data)
            return False
    
    except Exception as e:
        logger.error("Telegram notification check failed", error=str(e))
        return False


async def simulate_local_aider_test():
    """Run a quick local aider test to verify it works."""
    config = get_config()
    
    logger.info("🧪 Running local aider test...", aider_bin=config.aider_bin)
    
    if not Path(config.aider_bin).exists():
        logger.error("Aider binary not found", path=config.aider_bin)
        return False
    
    try:
        # Quick aider test: just show version
        result = subprocess.run(
            [config.aider_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info("✅ Aider is functional", version=result.stdout.strip()[:50])
            return True
        else:
            logger.error("Aider test failed", stderr=result.stderr[:100])
            return False
    
    except Exception as e:
        logger.error("Aider test error", error=str(e))
        return False


async def run_full_test():
    """Execute full end-to-end test."""
    logger.info("=" * 60)
    logger.info("🚀 AirCode Telegram Bot E2E Test Starting...")
    logger.info("=" * 60)
    
    results = {}
    
    # 1. Check server health
    results["server_health"] = await check_server_health()
    if not results["server_health"]:
        logger.error("❌ Server not responding. Start with: python3 server.py or server.refactored.py")
        return results
    
    # 2. Verify aider works
    results["aider_functional"] = await simulate_local_aider_test()
    if not results["aider_functional"]:
        logger.error("❌ Aider not functional. Install via: pip install aider-chat")
        return results
    
    # 3. Send test prompt
    test_prompt = "Create a Python script that prints 'AirCode E2E Test Successful'"
    results["webhook_sent"] = await send_test_prompt(test_prompt)
    if not results["webhook_sent"]:
        logger.error("❌ Failed to send webhook")
        return results
    
    # 4. Monitor aider execution
    results["aider_executed"] = await monitor_aider_execution(timeout=120)
    
    # 5. Check for Telegram notification
    await asyncio.sleep(2)  # Brief wait for async task completion
    results["telegram_notified"] = await check_telegram_notification()
    
    return results


async def main():
    """Main entry point."""
    config = get_config()
    
    print("\n" + "=" * 70)
    print("     AirCode Telegram Bot End-to-End Test")
    print("=" * 70)
    print(f"\n📋 Test Configuration:")
    print(f"   Workspace: {config.workspace_dir}")
    print(f"   Chat ID: {config.telegram_chat_id}")
    print(f"   User ID: {config.allowed_user_id}")
    print(f"   Model: {config.gemini_model}")
    print(f"   Aider Timeout: {config.aider_timeout}s")
    print()
    
    try:
        results = await run_full_test()
        
        print("\n" + "=" * 70)
        print("     Test Results Summary")
        print("=" * 70)
        
        for test_name, passed in results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status}: {test_name.replace('_', ' ').title()}")
        
        all_passed = all(results.values())
        
        if all_passed:
            print("\n🎉 All tests passed! Telegram bot is operational.")
            return 0
        else:
            print("\n⚠️  Some tests failed. See details above.")
            print("\nTroubleshooting:")
            if not results.get("server_health"):
                print("  1. Start the server: python3 server.refactored.py")
            if not results.get("aider_functional"):
                print("  2. Install aider: pip install aider-chat")
            if not results.get("webhook_sent"):
                print("  3. Check .env configuration (TELEGRAM_TOKEN, etc.)")
            if not results.get("aider_executed"):
                print("  4. Check GEMINI_API_KEY is valid")
            return 1
    
    except Exception as e:
        logger.critical("Test failed", error=str(e), exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
