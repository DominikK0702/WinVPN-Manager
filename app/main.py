import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core.powershell_backend import PowerShellRasBackend
from core.resources import app_logo_icon
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app_icon: QIcon = app_logo_icon()
    app.setWindowIcon(app_icon)
    backend = PowerShellRasBackend()
    window = MainWindow(backend)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
