"""
Centralized Logging Configuration — Info & Critical Log Segregation.

Configures console and structured date-based file logging:
- INFO logs -> logs/info/info_DD-MM-YYYY.log with format '[INFO] - DD-MM-YYYY HH:MM:SS - name: message'
- ERROR & CRITICAL logs -> logs/critical/critical_DD-MM-YYYY.log with format '[CRITICAL] - DD-MM-YYYY HH:MM:SS - name: message'
- Console (stdout) -> '[LEVEL] - DD-MM-YYYY HH:MM:SS - name: message'
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


class ExactInfoFilter(logging.Filter):
    """Filter that passes only INFO level log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.INFO


class CriticalOnlyFilter(logging.Filter):
    """Filter that passes ERROR and CRITICAL records to the critical log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


class CriticalFormatter(logging.Formatter):
    """
    Formatter for critical and error records.

    Ensures both ERROR and CRITICAL records are displayed with [CRITICAL] prefix
    without permanently altering the shared LogRecord level for other handlers.
    """

    def format(self, record: logging.LogRecord) -> str:
        orig_levelname = record.levelname
        record.levelname = "CRITICAL"
        try:
            return super().format(record)
        finally:
            record.levelname = orig_levelname


def get_log_directories(base_dir: Path | None = None) -> tuple[Path, Path]:
    """Return paths to info and critical log directories, creating them if needed."""
    if base_dir is None:
        # Default to backend root directory (backend/)
        base_dir = Path(__file__).resolve().parent.parent.parent
    logs_dir = base_dir / "logs"
    info_dir = logs_dir / "info"
    critical_dir = logs_dir / "critical"
    info_dir.mkdir(parents=True, exist_ok=True)
    critical_dir.mkdir(parents=True, exist_ok=True)
    return info_dir, critical_dir


def configure_logging(base_dir: Path | None = None) -> None:
    """
    Configures console, info file, and critical file log handlers.

    - Info logs: logs/info/info_<DD-MM-YYYY>.log
    - Critical logs: logs/critical/critical_<DD-MM-YYYY>.log
    """
    info_dir, critical_dir = get_log_directories(base_dir)

    today_str = datetime.now().strftime("%d-%m-%Y")
    info_log_file = info_dir / f"info_{today_str}.log"
    critical_log_file = critical_dir / f"critical_{today_str}.log"

    date_format = "%d-%m-%Y %H:%M:%S"
    log_format = "[%(levelname)s] - %(asctime)s - %(name)s: %(message)s"

    standard_formatter = logging.Formatter(log_format, datefmt=date_format)
    critical_formatter = CriticalFormatter(log_format, datefmt=date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    # 1. Console Output Handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(standard_formatter)
    stdout_handler.setLevel(logging.INFO)
    root_logger.addHandler(stdout_handler)

    # 2. Info File Handler (logs/info/info_<DD-MM-YYYY>.log)
    info_handler = logging.FileHandler(info_log_file, encoding="utf-8")
    info_handler.setFormatter(standard_formatter)
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(ExactInfoFilter())
    root_logger.addHandler(info_handler)

    # 3. Critical File Handler (logs/critical/critical_<DD-MM-YYYY>.log)
    critical_handler = logging.FileHandler(critical_log_file, encoding="utf-8")
    critical_handler.setFormatter(critical_formatter)
    critical_handler.setLevel(logging.ERROR)
    critical_handler.addFilter(CriticalOnlyFilter())
    root_logger.addHandler(critical_handler)
