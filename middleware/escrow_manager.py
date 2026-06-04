import httpx
from pathlib import Path
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("escrow_manager")
config = get_config()

async def trigger_escrow(chat_id: int, error_log: str):
    """
    Sends the Escrow payload (error logs + screenshots) to Telegram.
    """
    if not config.TELEGRAM_TOKEN:
        return False
        
    logger.info("⏸️ Escrow Manager triggered. Dispatching payload to Telegram...")
    
    workspace_dir = Path(config.WORKSPACE_DIR) / "workspace"
    media = []
    files = {}
    
    # Attach screenshots if they exist
    for idx, bp in enumerate(["mobile.png", "tablet.png", "desktop.png"]):
        img_path = workspace_dir / bp
        if img_path.exists():
            files[f"photo{idx}"] = (bp, open(img_path, "rb"), "image/png")
            media.append({
                "type": "photo",
                "media": f"attach://photo{idx}",
                "caption": f"Breakpoint: {bp.split('.')[0]}" if idx == 0 else ""
            })
            
    if media:
        media[0]["caption"] = f"⏸️ **ESCROW PAUSED**\n\nValidation failed 3 times. Engine is frozen.\n\n**Final Error:**\n{error_log[:500]}\n\n*Reply to this message with a text hint to resume execution, or type /abort.*"
        media[0]["parse_mode"] = "Markdown"
        
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMediaGroup"
        payload = {"chat_id": chat_id, "media": str(media).replace("'", '"')} # simple json conversion for media field
        
        # We need to construct a multipart request properly for httpx
        # actually for sendMediaGroup, it's slightly complex.
        # Alternatively, we can just send the first photo with a caption to keep it simple and robust.
        pass

    # Simple fallback: send 1 summary message and 1 collage or just the desktop photo
    # To keep it extremely robust without complex multipart mediagroup forms:
    img_path = workspace_dir / "desktop.png"
    if img_path.exists():
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendPhoto"
        with open(img_path, "rb") as f:
            await _send_photo(url, chat_id, f, error_log)
    else:
        # Just text
        await _send_text(chat_id, error_log)

async def _send_photo(url, chat_id, file, error_log):
    caption = f"⏸️ ESCROW PAUSED\n\nValidation failed 3 times. Engine is frozen.\n\nFinal Error:\n{error_log[:500]}\n\nReply with a hint to resume, or /abort."
    data = {"chat_id": chat_id, "caption": caption}
    files = {"photo": file}
    async with httpx.AsyncClient() as client:
        await client.post(url, data=data, files=files, timeout=15)

async def _send_text(chat_id, error_log):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    caption = f"⏸️ ESCROW PAUSED\n\nValidation failed 3 times. Engine is frozen.\n\nFinal Error:\n{error_log[:500]}\n\nReply with a hint to resume, or /abort."
    payload = {"chat_id": chat_id, "text": caption}
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, timeout=10)

def get_escrow_manager():
    return trigger_escrow
