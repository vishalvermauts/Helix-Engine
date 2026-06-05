import asyncio
import httpx
from pyngrok import ngrok
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("system_monitor")

class SystemMonitor:
    def __init__(self):
        self.config = get_config()
        self.active_tunnel_url = None

    async def start_ngrok_tunnel(self) -> str:
        """Start the pyngrok tunnel dynamically on port 8000."""
        try:
            logger.info("Starting PyNgrok tunnel...")
            # Run the blocking ngrok connect in a thread to prevent freezing the async loop
            tunnel = await asyncio.to_thread(ngrok.connect, self.config.PORT)
            url = tunnel.public_url
            logger.info(f"✅ PyNgrok Tunnel Established: {url}")
            return url
        except Exception as e:
            logger.error(f"Failed to start PyNgrok tunnel: {e}")
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
        """Background daemon that initializes ngrok and registers the webhook."""
        logger.info("System Monitor daemon starting...")
        
        # 1. Establish the PyNgrok tunnel
        public_url = await self.start_ngrok_tunnel()
        
        if public_url:
            self.active_tunnel_url = public_url
            # 2. Register it with Telegram
            await self.update_telegram_webhook(public_url)
            
        # 3. Idle to keep the daemon alive
        while True:
            await asyncio.sleep(3600)

    async def stop(self):
        """Clean up the ngrok tunnel on shutdown."""
        if self.active_tunnel_url:
            logger.info("Disconnecting PyNgrok tunnel...")
            await asyncio.to_thread(ngrok.disconnect, self.active_tunnel_url)
            await asyncio.to_thread(ngrok.kill)

def get_system_monitor() -> SystemMonitor:
    return SystemMonitor()
