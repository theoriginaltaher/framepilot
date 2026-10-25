from __future__ import annotations

import logging
from pathlib import Path
import sys


def configure_logging() -> Path:
    import os
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FramePilot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "framepilot.log"
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()])
    return path


def main() -> int:
    configure_logging()
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from framepilot.ui.main_window import MainWindow
    except ImportError as exc:
        logging.getLogger(__name__).exception("FramePilot GUI dependencies failed to import")
        print("FramePilot dependencies are missing. Run: py -3.12 -m pip install -e .", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 2
    app = QApplication(sys.argv)
    app.setApplicationName("FramePilot")
    app.setOrganizationName("FramePilot")
    window = MainWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
