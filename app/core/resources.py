import sys
from pathlib import Path

from PySide6.QtGui import QIcon

from core.logger import get_logger


def _resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def app_logo_icon() -> QIcon:
    logo_path = _resource_root() / "logo.png"
    icon = QIcon(str(logo_path))
    if icon.isNull():
        get_logger().warning("Could not load application icon from %s", logo_path)
    return icon
