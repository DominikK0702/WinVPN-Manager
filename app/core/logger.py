import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER = None


def _log_path() -> Path:
    base_dir = Path(sys.argv[0]).resolve().parent
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "winvpn-manager.log"


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("winvpn-manager")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        # Do not create local log files for frozen/packaged builds.
        if getattr(sys, "frozen", False):
            logger.addHandler(logging.NullHandler())
        else:
            handler = RotatingFileHandler(
                _log_path(),
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

    _LOGGER = logger
    return logger
