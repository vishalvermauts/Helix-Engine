import asyncio
import httpx
from pyngrok import ngrok
from lib.config import get_config
from lib.logging import get_logger
from agents.triage_router import get_triage_stats

logger = get_logger("system_monitor")



class SystemMonitor:
    def __init__(self):
        self.config = get_config()
        self.active_tunnel_url = None

    async def start_ngrok_tunnel(self) -> str:
        """Start the pyngrok tunnel dynamically on port 8000."""
        try:
            logger.info("Starting PyNgrok tunnel...")
            if self.config.NGROK_AUTHTOKEN:
                ngrok.set_auth_token(self.config.NGROK_AUTHTOKEN)
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

    # ─── Phase 4: Observability & Metrics ──────────────────────────────────────

    async def _collect_triage_stats(self) -> str:
        """
        Gather triage routing statistics from the in-memory TriageStats singleton.

        Returns a pre-formatted Telegram message string with the key metrics.
        Never raises — returns an error string on failure so the caller can still
        decide whether to send it.
        """
        try:
            stats = get_triage_stats()
            s = stats.summary_dict()

            counts = s["counts"]
            uptime_h = s["uptime_seconds"] // 3600
            uptime_m = (s["uptime_seconds"] % 3600) // 60

            report_lines = [
                "📊 *Triage Router Statistics*",
                f"⏱ Uptime: {uptime_h}h {uptime_m}m",
                f"📨 Total classified: {s['total_classified']}",
                f"🚧 Canary bypassed : {s.get('canary_bypassed', 0)}",
                "",
                "🗂 *Classification Breakdown:*",
                f"  • SIMPLE          : {counts.get('SIMPLE', 0)}",
                f"  • COMPLEX         : {counts.get('COMPLEX', 0)}",
                f"  • AGENT_GENERATION: {counts.get('AGENT_GENERATION', 0)}",
                f"  • QA_TESTING      : {counts.get('QA_TESTING', 0)}",
                "",
                f"💸 Estimated spend : ${s['total_cost_usd']:.4f}",
                f"💰 Savings vs all-Gemini: ${s['estimated_savings_usd']:.4f}",
                f"⚡ Simple ratio    : {s['simple_ratio_pct']}%",
                f"🏆 Peak SIMPLE/hr  : {s.get('peak_simple_per_hour', 0):.1f}",
                "",
                f"🕒 Session started : {s['session_start'][:19]}Z",
            ]

            report = "\n".join(report_lines)
            logger.info(
                "Triage stats collected",
                total=s["total_classified"],
                savings_usd=s["estimated_savings_usd"],
            )
            return report

        except Exception as e:
            logger.error("Triage stats collection failed", error=str(e))
            return f"⚠️ Triage stats unavailable: {e}"

    async def _send_telegram_message(self, text: str):
        """Send a Telegram message to the configured chat (best-effort)."""
        if not self.config.TELEGRAM_TOKEN or not self.config.ALLOWED_USER_ID:
            return
        url = f"https://api.telegram.org/bot{self.config.TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": self.config.ALLOWED_USER_ID,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json=payload)
        except Exception as e:
            logger.warning("Periodic stats Telegram send failed", error=str(e))

    async def send_triage_report(self):
        """Collect stats and send them to Telegram immediately (used by /triage command)."""
        report = await self._collect_triage_stats()
        await self._send_telegram_message(report)
        return report

    async def _periodic_triage_reporter(self):
        """Background coroutine that sends a triage stats report periodically.
        
        Interval is driven by config.TRIAGE_STATS_INTERVAL (default 3600s).
        """
        interval = getattr(self.config, "TRIAGE_STATS_INTERVAL", 3600)
        # Wait one full cycle before the first report so we have real data
        await asyncio.sleep(interval)
        while True:
            try:
                report = await self._collect_triage_stats()
                await self._send_telegram_message(report)
            except Exception as e:
                logger.error("Periodic triage reporter error", error=str(e))
            await asyncio.sleep(interval)

    # ───────────────────────────────────────────────────────────────────────────

    async def run_daemon(self):
        """Background daemon that initializes ngrok, registers the webhook,
        and starts the periodic triage stats reporter."""
        logger.info("System Monitor daemon starting...")
        
        # 1. Establish the PyNgrok tunnel
        public_url = await self.start_ngrok_tunnel()
        
        if public_url:
            self.active_tunnel_url = public_url
            # 2. Register it with Telegram
            await self.update_telegram_webhook(public_url)

        # 3. Start periodic triage reporting (fire-and-forget background task)
        asyncio.create_task(self._periodic_triage_reporter())
            
        # 4. Idle to keep the daemon alive
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
