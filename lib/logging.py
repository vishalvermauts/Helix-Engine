import json
import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Any

class HelixJSONFormatter(logging.Formatter):
    """Format logs as JSON for structured observability."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        if record.exc_info:
            log_obj["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
            
        if hasattr(record, "extra_fields"):
            log_obj.update(record.extra_fields)
            
        return json.dumps(log_obj)

class StructuredLogger:
    """Wrapper for structured logging with context."""
    def __init__(self, name: str, level: str = "INFO", format_type: str = "json"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.handlers.clear()
        
        # Determine format
        if format_type == "json":
            formatter = HelixJSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - [%(levelname)s] [%(module)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            
        # Console output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File output (persistent, rotating)
        os.makedirs("logs", exist_ok=True)
        file_handler = RotatingFileHandler(
            "logs/aircode.log", maxBytes=5*1024*1024, backupCount=3
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
    def _log(self, level_name: str, message: str, **context):
        level_val = getattr(logging, level_name)
        extra = {"extra_fields": context} if context else {}
        self.logger.log(level_val, message, extra=extra)

    def info(self, message: str, **context): self._log("INFO", message, **context)
    def error(self, message: str, **context): self._log("ERROR", message, **context)
    def warning(self, message: str, **context): self._log("WARNING", message, **context)
    def debug(self, message: str, **context): self._log("DEBUG", message, **context)
    def critical(self, message: str, **context): self._log("CRITICAL", message, **context)

_loggers: Dict[str, StructuredLogger] = {}

def get_logger(name: str, level: str = "INFO", format_type: str = "json") -> StructuredLogger:
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name, level, format_type)
    return _loggers[name]
