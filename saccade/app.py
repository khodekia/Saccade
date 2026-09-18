"""Application entry point.

Two ways to use the program:

* the GUI (default) -- ``saccade book.pdf``;
* a terminal previewer -- ``saccade --text book.pdf --page 12``, which prints
  a page with ANSI bold fixations, handy for a quick check without a display.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, bionic
from .document import BackendUnavailable, DocumentError, open_document
from .settings import Settings

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saccade",
        description="Read PDF books with bionic-reading fixations.",
    )
    parser.add_argument("pdf", nargs="?", help="PDF book to open")
    parser.add_argument("--page", type=int, default=None,
                        help="1-based page to start on")
    parser.add_argument("--backend", default=None,
                        help="force a text engine (PyMuPDF, pypdf, pdftotext)")
    parser.add_argument("--text", action="store_true",
                        help="print the page to the terminal instead of opening the GUI")
    parser.add_argument("--no-fixations", action="store_true",
                        help="print/read the page without bionic bolding")
    parser.add_argument("--intensity", type=float, default=bionic.DEFAULT_INTENSITY,
                        help=f"how much of each word to bold "
                             f"({bionic.MIN_INTENSITY}-{bionic.MAX_INTENSITY}, "
                             f"default {bionic.DEFAULT_INTENSITY})")
    parser.add_argument("--list-backends", action="store_true",
                        help="show which text engines are available and exit")
    parser.add_argument("--version", action="version", version=f"Saccade {__version__}")
    return parser


def _run_text_mode(args: argparse.Namespace) -> int:
    """Terminal preview: print one page with ANSI bold fixations."""
    if not args.pdf:
        print("saccade: --text needs a PDF file", file=sys.stderr)
        return 2
    try:
        with open_document(args.pdf, backend=args.backend) as document:
            page = (args.page or 1) - 1
            page = max(0, min(page, max(0, document.page_count - 1)))
            print(f"{document.display_title} \u2014 page {page + 1}/{document.page_count} "
                  f"({document.backend_name})")
            print()
            print(bionic.to_ansi(
                document.page_text(page),
                args.intensity,
                enabled=not args.no_fixations,
            ))
    except (DocumentError, BackendUnavailable) as exc:
        print(f"saccade: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Program entry point; returns the process exit code."""
    args = build_parser().parse_args(argv)

    if args.list_backends:
        from .document import available_backends, backend_names

        available = available_backends()
        for name in backend_names():
            mark = "\u2713" if name in available else "\u2717"
            print(f"  {mark}  {name}")
        return 0

    if args.text:
        return _run_text_mode(args)

    # Qt is imported here so that --text, --list-backends and --help work on a
    # machine where PyQt6 is not installed.
    from PyQt6.QtWidgets import QApplication

    from .support import app_icon
    from .theme import app_qss, get_theme, install_popup_corner_fix
    from .ui import MainWindow

    app = QApplication(sys.argv[:1] + (argv or sys.argv[1:]))
    app.setApplicationName("Saccade")
    app.setApplicationDisplayName("Saccade")
    app.setOrganizationName("saccade")
    app.setDesktopFileName("saccade")
    app.setWindowIcon(app_icon())
    # Modern chrome is themed; the reading page keeps its own paper colour.
    app.setStyleSheet(app_qss(get_theme(Settings().theme)))
    # Round off the square window-manager edges on menus and combo box drop-downs.
    install_popup_corner_fix(app)

    settings = Settings()
    page = None if args.page is None else max(0, args.page - 1)
    window = MainWindow(settings, args.pdf, page)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())