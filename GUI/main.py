"""ALBATROSS GUI entry point.

Run:      python main.py
Config:   config.yaml (set app.simulation to false when connecting real hardware)
"""
import sys
from PyQt6.QtWidgets import QApplication
from albatross.config import load_config
from albatross.ui.main_window import MainWindow


def main():
    cfg = load_config()
    app = QApplication(sys.argv)
    win = MainWindow(cfg)
    win.show()
    # Headless self-check (development sanity check): python main.py --smoke
    if "--smoke" in sys.argv:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(800, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
