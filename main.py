import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from window import MainWindow

if __name__ == "__main__":
    startup_paths = sys.argv[1:]
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    if startup_paths:
        QTimer.singleShot(
            0, lambda: win.open_external_paths(startup_paths, "启动参数")
        )
    sys.exit(app.exec_())
