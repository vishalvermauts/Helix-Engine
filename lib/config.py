import os
import copy
from dataclasses import dataclass, field, asdict
from typing import Dict, Any

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

@dataclass
class HelixConfig:
    # API Keys & Secrets (Will be scrubbed)
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    TELEGRAM_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    DEEPSEEK_API_KEY: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    NGROK_AUTHTOKEN: str = field(default_factory=lambda: os.getenv("NGROK_AUTHTOKEN", ""))

    # Core Settings
    GEMINI_API_BASE: str = field(default_factory=lambda: os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"))
    GEMINI_MODEL: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-pro"))
    DEEPSEEK_API_BASE: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"))
    WORKSPACE_DIR: str = field(default_factory=lambda: os.getenv("WORKSPACE_DIR", "/workspaces/AirCode"))
    AIDER_BIN: str = field(default_factory=lambda: os.getenv("AIDER_BIN", "/home/vboxuser/.local/bin/aider"))
    
    # Typed Settings
    ALLOWED_USER_ID: int = field(default=0)
    AIDER_TIMEOUT: int = field(default=300)
    PORT: int = field(default=8000)
    TRIAGE_ENABLED: bool = field(default=True)
    TRIAGE_TIMEOUT: float = field(default=1.5)
    # Phase 5: Canary gate — 0.0 routes no traffic through triage, 1.0 routes all
    # Set to e.g. 0.25 to start canary at 25% before going 100%
    TRIAGE_CANARY_RATE: float = field(default=1.0)
    # Safety fallback model if triage fails or is disabled
    TRIAGE_FALLBACK_MODEL: str = field(default_factory=lambda: os.getenv("TRIAGE_FALLBACK_MODEL", "gemini/gemini-2.5-pro"))
    # Phase 5: How often (seconds) to send periodic triage stats to Telegram
    TRIAGE_STATS_INTERVAL: int = field(default=3600)
    # Phase 6: Optional Claude routing (leave blank to disable)
    CLAUDE_API_KEY: str = field(default_factory=lambda: os.getenv("CLAUDE_API_KEY", ""))
    CLAUDE_MODEL: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022"))

    # Vertex AI Configuration
    VERTEX_PROJECT: str = field(default_factory=lambda: os.getenv("VERTEX_PROJECT", os.getenv("VERTEXAI_PROJECT", "")))
    VERTEX_LOCATION: str = field(default_factory=lambda: os.getenv("VERTEX_LOCATION", os.getenv("VERTEXAI_LOCATION", "us-central1")))

    @property
    def VERTEX_ENABLED(self) -> bool:
        return bool(self.VERTEX_PROJECT)


    def __post_init__(self):
        # Type coercion logic
        self.ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", self.ALLOWED_USER_ID))
        self.AIDER_TIMEOUT = int(os.getenv("AIDER_TIMEOUT", self.AIDER_TIMEOUT))
        self.PORT = int(os.getenv("PORT", self.PORT))
        self.TRIAGE_TIMEOUT = float(os.getenv("TRIAGE_TIMEOUT", self.TRIAGE_TIMEOUT))
        self.TRIAGE_STATS_INTERVAL = int(os.getenv("TRIAGE_STATS_INTERVAL", self.TRIAGE_STATS_INTERVAL))
        
        raw_canary = os.getenv("TRIAGE_CANARY_RATE", str(self.TRIAGE_CANARY_RATE))
        try:
            self.TRIAGE_CANARY_RATE = max(0.0, min(1.0, float(raw_canary)))
        except ValueError:
            self.TRIAGE_CANARY_RATE = 1.0
        
        triage_env = os.getenv("TRIAGE_ENABLED", str(self.TRIAGE_ENABLED)).lower()
        self.TRIAGE_ENABLED = triage_env in ("true", "1", "yes")

    def to_dict(self) -> Dict[str, Any]:
        """Safely serialize config while scrubbing secrets."""
        data = asdict(self)
        # Redact secrets
        for secret_key in ["GEMINI_API_KEY", "TELEGRAM_TOKEN", "DEEPSEEK_API_KEY", "NGROK_AUTHTOKEN", "CLAUDE_API_KEY"]:
            if data.get(secret_key):
                data[secret_key] = "***REDACTED***"
            else:
                data[secret_key] = "NOT_SET"
        return data

# Global singleton
_config_instance = None

def get_config(force_reload: bool = False) -> HelixConfig:
    global _config_instance
    if _config_instance is None or force_reload:
        load_dotenv(override=True)
        _config_instance = HelixConfig()
    return _config_instance

def reload_config() -> HelixConfig:
    """Trigger a runtime configuration reload."""
    return get_config(force_reload=True)
