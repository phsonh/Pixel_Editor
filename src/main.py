import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon

from window import MainWindow


def resource_path(*parts):
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent
    return base_path.joinpath(*parts)


if __name__ == "__main__":
    startup_paths = sys.argv[1:]
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(
        QIcon(str(resource_path("assets", "pixel_editor_logo.png")))
    )
    win = MainWindow()
    win.show()
    if startup_paths:
        QTimer.singleShot(
            0, lambda: win.open_external_paths(startup_paths, "启动参数")
        )
    sys.exit(app.exec_())
