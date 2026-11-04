"""Render the README screenshots from docs/demo.pdf, without needing a display.

Run it with:  python tools/make_screenshots.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from saccade.settings import Settings
from saccade.theme import app_qss, get_theme, install_popup_corner_fix
from saccade.ui import MainWindow

OUT = os.path.join(ROOT, "docs", "screenshots")
DEMO = os.path.join(ROOT, "docs", "demo.pdf")

#: Kept alive to the end: destroying a window on the way out can crash Qt's
#: offscreen plugin before the output is flushed.
_windows = []

#: name, 0-based page, and the settings that differ from the defaults.
SHOTS = (
    ("reading.png", 0, {"theme": "paper"}),
    ("formulas.png", 1, {"theme": "paper"}),
    ("focus-mode.png", 0, {"theme": "paper", "focus_mode": True}),
    ("night.png", 1, {"theme": "night"}),
    ("easy-reading.png", 0, {"theme": "sepia", "font_size": 17, "line_height": 1.8,
                             "letter_spacing": 1.0, "word_spacing": 3.0,
                             "focus_mode": True}),
)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    install_popup_corner_fix(app)
    with tempfile.TemporaryDirectory() as folder:
        for number, (name, page, options) in enumerate(SHOTS):
            ini = os.path.join(folder, f"{number}.ini")
            settings = Settings(QSettings(ini, QSettings.Format.IniFormat))
            settings.font_size = 15
            settings.column_width = 620
            for key, value in options.items():
                setattr(settings, key, value)
            app.setStyleSheet(app_qss(get_theme(settings.theme)))
            window = MainWindow(settings)
            window.resize(1180, 860)
            window.show()
            window.open_path(DEMO, page)
            app.processEvents()
            path = os.path.join(OUT, name)
            window.grab().save(path)
            print("wrote", path, flush=True)
            _windows.append(window)
    return 0


if __name__ == "__main__":
    code = main()
    # Skip interpreter teardown: Qt's offscreen plugin can crash during it, long
    # after the files are safely written.
    os._exit(code)
