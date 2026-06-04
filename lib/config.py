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

    # Core Settings
    GEMINI_API_BASE: str = field(default="https://generativelanguage.googleapis.com/v1beta")
    GEMINI_MODEL: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-pro"))
    DEEPSEEK_API_BASE: str = field(default="https://api.deepseek.com/v1")
    WORKSPACE_DIR: str = field(default_factory=lambda: os.getenv("WORKSPACE_DIR", "/workspaces/AirCode"))
    AIDER_BIN: str = field(default_factory=lambda: os.getenv("AIDER_BIN", "/home/vboxuser/.local/bin/aider"))
    
    # Typed Settings
    ALLOWED_USER_ID: int = field(default=0)
    AIDER_TIMEOUT: int = field(default=300)
    PORT: int = field(default=8000)
    TRIAGE_ENABLED: bool = field(default=True)
    TRIAGE_TIMEOUT: float = field(default=1.5)

    def __post_init__(self):
        # Type coercion logic
        self.ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", self.ALLOWED_USER_ID))
        self.AIDER_TIMEOUT = int(os.getenv("AIDER_TIMEOUT", self.AIDER_TIMEOUT))
        self.PORT = int(os.getenv("PORT", self.PORT))
        self.TRIAGE_TIMEOUT = float(os.getenv("TRIAGE_TIMEOUT", self.TRIAGE_TIMEOUT))
        
        triage_env = os.getenv("TRIAGE_ENABLED", str(self.TRIAGE_ENABLED)).lower()
        self.TRIAGE_ENABLED = triage_env in ("true", "1", "yes")

    def to_dict(self) -> Dict[str, Any]:
        """Safely serialize config while scrubbing secrets."""
        data = asdict(self)
        # Redact secrets
        for secret_key in ["GEMINI_API_KEY", "TELEGRAM_TOKEN", "DEEPSEEK_API_KEY"]:
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
