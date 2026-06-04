import asyncio
import re
import httpx
from pathlib import Path

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("system_monitor")
config = get_config()

class SystemMonitor:
    def __init__(self):
        self.config = get_config()
        self.active_tunnel_url = None
        self.log_path = Path(self.config.WORKSPACE_DIR) / "cloudflare.log"

    async def scan_for_tunnel(self) -> str:
        """Scan cloudflare.log for the active trycloudflare.com URL."""
        if not self.log_path.exists():
            logger.debug(f"Tunnel log not found at {self.log_path}")
            return None

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Read from bottom up to get the most recent URL
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            for line in reversed(lines):
                match = url_pattern.search(line)
                if match:
                    return match.group(0)
        except Exception as e:
            logger.error(f"Error reading cloudflare.log: {e}")
            
        return None

    async def update_telegram_webhook(self, url: str):
        """Register the new webhook URL with Telegram."""
        if not self.config.TELEGRAM_TOKEN:
            logger.error("No Telegram token configured. Cannot set webhook.")
            return

        webhook_url = f"{url}/webhook"
        api_url = f"https://api.telegram.org/bot{self.config.TELEGRAM_TOKEN}/setWebhook"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url, json={"url": webhook_url})
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    logger.info(f"Telegram webhook updated to: {webhook_url}")
                else:
                    logger.error(f"Telegram setWebhook failed: {data}")
        except Exception as e:
            logger.error(f"Failed to communicate with Telegram API: {e}")

    async def run_daemon(self):
        """Background loop to self-heal the webhook connection."""
        logger.info("System Monitor daemon starting...")
        while True:
            current_url = await self.scan_for_tunnel()
            if current_url and current_url != self.active_tunnel_url:
                logger.info(f"Detected new tunnel URL: {current_url}")
                self.active_tunnel_url = current_url
                await self.update_telegram_webhook(current_url)
            
            await asyncio.sleep(10)

def get_system_monitor() -> SystemMonitor:
    return SystemMonitor()
