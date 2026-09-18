"""Headless GUI smoke test: drive the real window and save screenshots.

Run it with::

    .venv/bin/python tools/smoke_gui.py              # uses a generated sample book
    .venv/bin/python tools/smoke_gui.py mybook.pdf

It renders the actual window with Qt's ``offscreen`` platform plugin, exercises
paging, settings, search and screenshots, then prints a short report.  Useful on
a machine without a display (CI, ssh) and for checking that bionic fixations are
really applied.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless smoke test for the reader")
    parser.add_argument("pdf", nargs="?", help="PDF to open (a sample is generated if omitted)")
    parser.add_argument("--outdir", default=os.path.join(ROOT, "screenshots"),
                        help="where to write the screenshots")
    args = parser.parse_args(argv)

    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from saccade.settings import Settings
    from saccade.ui import MainWindow

    os.makedirs(args.outdir, exist_ok=True)

    pdf = args.pdf
    if not pdf:
        from tests import pdf_fixture

        pdf = os.path.join(args.outdir, "sample-book.pdf")
        pdf_fixture.build_book(pdf)
        print(f"generated sample book: {pdf}")

    app = QApplication(sys.argv[:1])
    # Isolated settings file so the smoke test cannot touch real preferences.
    ini = os.path.join(args.outdir, "smoke.ini")
    if os.path.exists(ini):
        os.remove(ini)  # a bookmark left by an earlier run would fail the check
    settings = Settings(QSettings(ini, QSettings.Format.IniFormat))
    window = MainWindow(settings)
    window.resize(1180, 820)

    if not window.open_path(pdf):
        print("FAIL: could not open the document")
        return 1

    def shot(name: str) -> str:
        app.processEvents()
        path = os.path.join(args.outdir, name)
        window.grab().save(path)
        print(f"screenshot: {path}")
        return path

    # -- checks ---------------------------------------------------------- #
    checks: list[tuple[str, bool]] = []
    checks.append(("document opened", window.document is not None))
    checks.append(("window title set", "\u2014 Saccade" in window.windowTitle()))
    first_html = window.view.toHtml()
    # Qt's toHtml() renders the fixation spans as ``font-weight:700``.
    checks.append(("bionic fixations rendered",
                   "font-weight:700" in first_html.replace(" ", "")))
    checks.append(("page text visible", "Bionic" in window.view.plain_text))
    checks.append(("status shows page 1",
                   "Page 1" in window.status_page.text()))
    checks.append(("chapter outline loaded",
                   window.sidebar.chapters.has_entries()
                   or window.document.backend_name == "pdftotext"))

    shot("01-paper-theme.png")

    # Paging
    window.turn_page(+1)
    app.processEvents()
    checks.append(("next page works", window.page == 1))
    checks.append(("hyphenated word was re-joined",
                   "example" in window.view.plain_text))
    window.goto_last_page()
    app.processEvents()
    checks.append(("last page works", window.page == window.document.page_count - 1))
    window.goto_page(0)

    # Bionic off/on and intensity
    window.act_bionic.setChecked(False)
    window.toggle_bionic()
    app.processEvents()
    checks.append(("fixations can be switched off",
                   "font-weight:700" not in window.view.toHtml().replace(" ", "")))
    window.act_bionic.setChecked(True)
    window.toggle_bionic()
    window.intensity_slider.setValue(70)
    app.processEvents()
    checks.append(("intensity applied", abs(window.settings.intensity - 0.7) < 1e-6))
    window.intensity_slider.setValue(int(0.5 * 100))

    # Appearance
    window.set_theme("night")
    app.processEvents()
    checks.append(("night theme applied", window.settings.theme == "night"))
    shot("02-night-theme.png")
    window.size_spin.setValue(18)
    window.font_combo.setCurrentText("Liberation Sans")
    app.processEvents()
    shot("03-large-sans.png")
    window.act_zen.setChecked(True)
    window.toggle_zen()
    app.processEvents()
    shot("04-zen-mode.png")
    window.toggle_zen()

    # Search
    window.find_edit.setText("hyphenated")
    window.start_search()
    worker = window._search_worker
    if worker is not None:
        worker.wait(15000)
    app.processEvents()
    hits = window.sidebar.results.hits
    checks.append(("search found the term", len(hits) >= 1))
    shot("05-search-highlight.png")

    # Bookmarks
    window.add_bookmark()
    marks = settings.bookmarks(window.document.path)
    checks.append(("bookmark stored",
                   len(marks) == 1 and marks[0][0] == window.page))

    # Restore a book at the remembered page
    window.goto_page(0)
    window.close()
    app.processEvents()

    print()
    width = max(len(name) for name, _ in checks)
    failed = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}")
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    if "sample" not in args.outdir.lower() and not args.pdf:
        os.remove(pdf)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())