"""The reader window: menus, toolbar, sidebar, paging and search."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSlider,
    QSpinBox,
    QToolBar,
)

from .. import __version__, bionic
from .. import layout as page_layout
from ..document import Document, DocumentError, open_document
from ..settings import (
    DEFAULT_COLUMN_WIDTH,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_LINE_HEIGHT,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    FONT_PACKAGES,
    Settings,
    available_fonts,
    installed_accessible_fonts,
)
from ..theme import (
    DEFAULT_THEME,
    app_qss,
    available_themes,
    get_theme,
    style_combo_popup,
)
from .reader_view import ReadingView
from .search import SearchHit, SearchWorker
from .sidebar import Sidebar

__all__ = ["MainWindow"]

WELCOME_TEXT = (
    "Hello, and welcome to Saccade.\n\n"
    "Drop a PDF onto this window, or press Ctrl+O to pick one. The start of "
    "every word is bolded to give your eye something to hold on to; the slider "
    "up in the toolbar decides how much, and Ctrl+B turns it off if you would "
    "rather compare. Press N for the next page and B for the one before.\n\n"
    "If a page ever feels like hard work, open the View menu and choose "
    "Easy-reading setup. It makes the text bigger, the line shorter, the "
    "spacing wider, and dims everything except the paragraph you are reading. "
    "Nothing there is permanent: Reset reading settings puts it all back.\n\n"
    "Saccade remembers where you stopped, so you can just close it and come "
    "back later. Happy reading."
)


class MainWindow(QMainWindow):
    """The application window."""

    def __init__(self, settings: Settings, path: str | None = None,
                 page: int | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.document: Document | None = None
        self.page = 0
        self._search_worker: SearchWorker | None = None
        self._zen = False

        self.setWindowTitle("Saccade")
        self.setAcceptDrops(True)
        self.setMinimumSize(640, 480)

        self.view = ReadingView(self)
        self.setCentralWidget(self.view)
        self.view.page_turn_requested.connect(self.turn_page)
        self.view.zoom_requested.connect(self.zoom)
        self.view.anchorClicked.connect(self._on_link)

        self.sidebar = Sidebar(self)
        self.dock = QDockWidget("Library", self)
        self.dock.setObjectName("libraryDock")
        self.dock.setWidget(self.sidebar)
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock)
        self.sidebar.page_requested.connect(self.goto_page)
        self.sidebar.bookmark_add_requested.connect(self.add_bookmark)
        self.sidebar.bookmark_remove_requested.connect(self.remove_bookmark)

        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self._build_statusbar()

        self._restore_window_state()
        self._apply_reading_settings()
        self._update_actions()

        if path:
            QTimer.singleShot(0, lambda: self.open_path(path, page))
        else:
            self._show_welcome()

    # ------------------------------------------------------------------ #
    # Construction helpers
    # ------------------------------------------------------------------ #
    def _act(
        self,
        text: str,
        *,
        shortcut: str | None = None,
        slot=None,
        checkable: bool = False,
        tip: str = "",
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot is not None:
            action.triggered.connect(slot)
        action.setCheckable(checkable)
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(tip)
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        return action

    def _build_actions(self) -> None:
        s = self.settings

        self.act_open = self._act("&Open book\u2026", shortcut="Ctrl+O",
                                  slot=self.open_dialog, tip="Open a PDF book")
        self.act_close = self._act("&Close book", shortcut="Ctrl+W",
                                   slot=self.close_document)
        self.act_quit = self._act("&Quit", shortcut="Ctrl+Q", slot=self.close)

        self.act_prev = self._act("\u25c0 Previous page", shortcut="B",
                                  slot=lambda: self.turn_page(-1),
                                  tip="Previous page (B)")
        self.act_next = self._act("Next page \u25b6", shortcut="N",
                                  slot=lambda: self.turn_page(+1),
                                  tip="Next page (N)")
        self.act_prev.setShortcuts([QKeySequence("B"), QKeySequence("Ctrl+Left")])
        self.act_next.setShortcuts([QKeySequence("N"), QKeySequence("Ctrl+Right")])
        self.act_prev_pg = self._act("Previous page (PgUp)", shortcut="PgUp",
                                     slot=lambda: self.turn_page(-1))
        self.act_next_pg = self._act("Next page (PgDown)", shortcut="PgDown",
                                     slot=lambda: self.turn_page(+1))
        self.act_first = self._act("&First page", shortcut="Ctrl+Home",
                                   slot=lambda: self.goto_page(0))
        self.act_last = self._act("&Last page", shortcut="Ctrl+End",
                                  slot=self.goto_last_page)
        self.act_next_chapter = self._act("Next c&hapter", shortcut="Ctrl+Down",
                                          slot=lambda: self.jump_chapter(+1))
        self.act_prev_chapter = self._act("Previous ch&apter", shortcut="Ctrl+Up",
                                          slot=lambda: self.jump_chapter(-1))

        self.act_zoom_in = self._act("&Bigger text", shortcut="Ctrl+=",
                                     slot=lambda: self.zoom(+1))
        self.act_zoom_out = self._act("&Smaller text", shortcut="Ctrl+-",
                                      slot=lambda: self.zoom(-1))
        self.act_zoom_reset = self._act("&Normal text size", shortcut="Ctrl+0",
                                        slot=self.reset_zoom)

        # Ctrl+B is the natural "bold" shortcut and bolding is what this reader
        # does, so bookmarks live on Ctrl+D.
        self.act_bionic = self._act(
            "&Bionic fixations", shortcut="Ctrl+B", slot=self.toggle_bionic,
            checkable=True, tip="Bold the first part of every word (Ctrl+B)",
        )
        self.act_bionic.setChecked(s.bionic_enabled)

        self.act_justify = self._act("&Justified text", slot=self.toggle_justify,
                                     checkable=True)
        self.act_justify.setChecked(s.justify)
        self.act_faithful = self._act(
            "Keep the page &layout", shortcut="Ctrl+L", slot=self.toggle_faithful,
            checkable=True,
            tip="Show each page the way it was typeset, instead of re-flowed text "
                "(Ctrl+L)",
        )
        self.act_faithful.setChecked(s.faithful_layout)
        self.act_smart_paragraphs = self._act(
            "Detect &paragraphs automatically", slot=self.toggle_smart_paragraphs,
            checkable=True, tip="Use first-line indentation to find paragraphs",
        )
        self.act_smart_paragraphs.setChecked(s.smart_paragraphs)

        self.act_line_up = self._act("Increase line spacing",
                                     slot=lambda: self.adjust_line_height(+0.1))
        self.act_line_down = self._act("Decrease line spacing",
                                       slot=lambda: self.adjust_line_height(-0.1))
        self.act_letter_up = self._act("Increase letter spacing",
                                       shortcut="Ctrl+Alt+=",
                                       slot=lambda: self.adjust_letter_spacing(+0.5),
                                       tip="Wider gaps between letters (Ctrl+Alt+=)")
        self.act_letter_down = self._act("Decrease letter spacing",
                                         shortcut="Ctrl+Alt+-",
                                         slot=lambda: self.adjust_letter_spacing(-0.5))
        self.act_word_up = self._act("Increase word spacing",
                                     slot=lambda: self.adjust_word_spacing(+1.0))
        self.act_word_down = self._act("Decrease word spacing",
                                       slot=lambda: self.adjust_word_spacing(-1.0))

        self.act_focus = self._act(
            "&Focus mode", shortcut="F2", slot=self.toggle_focus_mode,
            checkable=True,
            tip="Dim everything except the paragraph you are reading (F2)",
        )
        self.act_focus.setChecked(s.focus_mode)

        self.act_comfort = self._act(
            "Easy-reading &setup", slot=self.apply_comfort_preset,
            tip="Larger text, wider spacing, warm page and focus mode, in one go",
        )
        self.act_reset_reading = self._act("Reset reading settings",
                                           slot=self.reset_reading_settings)
        self.act_column_wider = self._act("Wider text column",
                                          shortcut="Ctrl+Shift+=",
                                          slot=lambda: self.adjust_column(+60))
        self.act_column_narrower = self._act("Narrower text column",
                                             shortcut="Ctrl+Shift+-",
                                             slot=lambda: self.adjust_column(-60))

        self.act_find = self._act("&Find in book\u2026", shortcut="Ctrl+F",
                                  slot=self.focus_search)
        self.act_find_next = self._act("Find &next result", shortcut="F3",
                                       slot=lambda: self.goto_search_hit(+1))
        self.act_find_prev = self._act("Find &previous result", shortcut="Shift+F3",
                                       slot=lambda: self.goto_search_hit(-1))
        self.act_find_case = self._act("Case sensitive", checkable=True,
                                       slot=self.restart_search)
        # No shortcut: the search field handles Return itself.
        self.act_search = self._act("Search the whole book", slot=self.start_search)

        self.act_bookmark_add = self._act("&Bookmark this page", shortcut="Ctrl+D",
                                          slot=self.add_bookmark,
                                          tip="Bookmark the current page (Ctrl+D)")
        self.act_bookmark_remove = self._act("Remove bookmark for this page",
                                             shortcut="Ctrl+Shift+D",
                                             slot=self.remove_current_bookmark)

        self.act_sidebar = self._act("Show &library panel", shortcut="F9",
                                     slot=self.toggle_sidebar, checkable=True)
        self.act_sidebar.setChecked(s.sidebar_visible)
        self.act_zen = self._act("&Zen mode", shortcut="F11", slot=self.toggle_zen,
                                 tip="Hide everything but the text (F11)")
        self.act_chapters = self._act("Show &chapters", shortcut="F4",
                                      slot=self.show_chapters)
        self.act_results = self._act("Show search &results", shortcut="F5",
                                     slot=self.show_results_panel)
        self.act_copy_page = self._act("&Copy page text", shortcut="Ctrl+Shift+C",
                                       slot=self.copy_page_text)
        self.act_copy_bionic = self._act("Copy page with fixations",
                                         slot=self.copy_bionic_text)

        self.act_about = self._act("&About Saccade", slot=self.show_about)
        self.act_repo = self._act("Project &homepage", slot=self.open_repo,
                                  tip="Open the Saccade source repository")
        self.act_shortcuts = self._act("&Keyboard shortcuts", shortcut="F1",
                                       slot=self.show_shortcuts)
        self.act_backends = self._act("Text &engines\u2026", slot=self.show_backends)
        self.act_reading_fonts = self._act("&Reading fonts\u2026",
                                           slot=self.show_reading_fonts)

        # Theme actions (exclusive radio group).
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for theme in available_themes():
            action = self._act(theme.label, checkable=True)
            action.setChecked(theme.key == s.theme)
            action.triggered.connect(lambda _checked, key=theme.key: self.set_theme(key))
            self.theme_group.addAction(action)
            self.theme_actions[theme.key] = action

    # ------------------------------------------------------------------ #
    # Toolbar, menus, status bar
    # ------------------------------------------------------------------ #
    def _build_toolbar(self) -> None:
        bar = QToolBar("Reading", self)
        bar.setObjectName("readingToolBar")
        bar.setMovable(False)
        self.addToolBar(bar)
        self.toolbar = bar

        bar.addAction(self.act_open)
        bar.addSeparator()
        bar.addAction(self.act_prev)

        self.page_spin = QSpinBox(self)
        self.page_spin.setRange(1, 1)
        self.page_spin.setToolTip("Go to page")
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.valueChanged.connect(self._on_page_spin)
        bar.addWidget(self.page_spin)

        self.page_total = QLabel("/ 0", self)
        self.page_total.setMinimumWidth(60)
        bar.addWidget(self.page_total)
        bar.addAction(self.act_next)
        bar.addSeparator()

        bar.addAction(self.act_bionic)
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.intensity_slider.setRange(
            int(bionic.MIN_INTENSITY * 100), int(bionic.MAX_INTENSITY * 100)
        )
        self.intensity_slider.setValue(int(self.settings.intensity * 100))
        self.intensity_slider.setFixedWidth(110)
        self.intensity_slider.setToolTip(
            "How much of each word is bolded (the classic fixation table is 50)"
        )
        self.intensity_slider.valueChanged.connect(self._on_intensity)
        bar.addWidget(self.intensity_slider)

        self.intensity_label = QLabel(f"{self.intensity_slider.value()}%", self)
        self.intensity_label.setMinimumWidth(38)
        bar.addWidget(self.intensity_label)
        bar.addSeparator()

        self.font_combo = QComboBox(self)
        self.font_combo.setToolTip("Reading font")
        families = available_fonts()
        self.font_combo.addItems(families)
        current = self.settings.font_family
        if current not in families:
            self.font_combo.addItem(current)
        self.font_combo.setCurrentText(current)
        self.font_combo.currentTextChanged.connect(self._on_font_family)
        bar.addWidget(self.font_combo)

        self.size_spin = QSpinBox(self)
        self.size_spin.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self.size_spin.setValue(self.settings.font_size)
        self.size_spin.setToolTip("Font size in points")
        self.size_spin.setSuffix(" pt")
        self.size_spin.setKeyboardTracking(False)
        self.size_spin.valueChanged.connect(self._on_font_size)
        bar.addWidget(self.size_spin)
        bar.addSeparator()

        self.theme_combo = QComboBox(self)
        self.theme_combo.setToolTip("Colour theme")
        for theme in available_themes():
            self.theme_combo.addItem(theme.label, theme.key)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.settings.theme))
        )
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo)
        bar.addWidget(self.theme_combo)
        bar.addSeparator()

        self.find_edit = QLineEdit(self)
        self.find_edit.setPlaceholderText("Search this book\u2026  (Ctrl+F)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMinimumWidth(190)
        self.find_edit.returnPressed.connect(self.start_search)
        self.find_edit.textChanged.connect(self._on_find_text_changed)
        bar.addWidget(self.find_edit)
        bar.addAction(self.act_find_prev)
        bar.addAction(self.act_find_next)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.act_open)
        self.recent_menu = file_menu.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)
        file_menu.addSeparator()
        file_menu.addAction(self.act_copy_page)
        file_menu.addAction(self.act_copy_bionic)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        go_menu = self.menuBar().addMenu("&Go")
        go_menu.addAction(self.act_prev)
        go_menu.addAction(self.act_next)
        go_menu.addAction(self.act_prev_pg)
        go_menu.addAction(self.act_next_pg)
        go_menu.addSeparator()
        go_menu.addAction(self.act_prev_chapter)
        go_menu.addAction(self.act_next_chapter)
        go_menu.addSeparator()
        go_menu.addAction(self.act_first)
        go_menu.addAction(self.act_last)
        go_menu.addAction(self.act_bookmark_add)
        go_menu.addAction(self.act_bookmark_remove)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.act_comfort)
        view_menu.addAction(self.act_focus)
        view_menu.addSeparator()
        view_menu.addAction(self.act_faithful)
        view_menu.addAction(self.act_bionic)
        view_menu.addAction(self.act_justify)
        view_menu.addAction(self.act_smart_paragraphs)
        view_menu.addSeparator()
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_reset)
        view_menu.addAction(self.act_line_up)
        view_menu.addAction(self.act_line_down)
        view_menu.addAction(self.act_letter_up)
        view_menu.addAction(self.act_letter_down)
        view_menu.addAction(self.act_word_up)
        view_menu.addAction(self.act_word_down)
        view_menu.addAction(self.act_column_wider)
        view_menu.addAction(self.act_column_narrower)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("&Theme")
        for action in self.theme_actions.values():
            theme_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.act_sidebar)
        view_menu.addAction(self.act_zen)
        view_menu.addSeparator()
        view_menu.addAction(self.act_reset_reading)

        search_menu = self.menuBar().addMenu("&Search")
        search_menu.addAction(self.act_find)
        search_menu.addAction(self.act_search)
        search_menu.addAction(self.act_find_case)
        search_menu.addSeparator()
        search_menu.addAction(self.act_find_next)
        search_menu.addAction(self.act_find_prev)
        search_menu.addSeparator()
        search_menu.addAction(self.act_chapters)
        search_menu.addAction(self.act_results)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.act_shortcuts)
        help_menu.addAction(self.act_reading_fonts)
        help_menu.addAction(self.act_backends)
        help_menu.addAction(self.act_repo)
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.status_book = QLabel("No book open", self)
        self.status_book.setMinimumWidth(180)
        bar.addWidget(self.status_book, 1)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)
        self.progress.setToolTip("Progress through the book")
        bar.addPermanentWidget(self.progress)

        self.status_page = QLabel("", self)
        self.status_page.setMinimumWidth(190)
        bar.addPermanentWidget(self.status_page)

        self.status_detail = QLabel("", self)
        self.status_detail.setMinimumWidth(140)
        bar.addPermanentWidget(self.status_detail)

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.settings.recent_files()
        if not files:
            action = self.recent_menu.addAction("No recent books")
            action.setEnabled(False)
            return
        for path in files:
            action = self.recent_menu.addAction(os.path.basename(path))
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_path(p))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear list")
        clear.triggered.connect(self._clear_recent)

    # ------------------------------------------------------------------ #
    # Opening and closing books
    # ------------------------------------------------------------------ #
    def open_dialog(self) -> None:
        start_dir = os.path.expanduser("~")
        recent = self.settings.recent_files()
        if recent:
            start_dir = os.path.dirname(recent[0])
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a PDF book", start_dir, "PDF documents (*.pdf);;All files (*)"
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str, page: int | None = None) -> bool:
        """Open *path*; returns True on success."""
        self._cancel_search()
        try:
            document = open_document(
                path, smart_paragraphs=self.settings.smart_paragraphs
            )
        except DocumentError as exc:
            QMessageBox.critical(self, "Cannot open book", str(exc))
            return False
        except Exception as exc:  # pragma: no cover - unexpected backend failure
            QMessageBox.critical(
                self, "Cannot open book",
                f"{os.path.basename(path)} could not be read:\n{exc}",
            )
            return False

        # Remember the position of the book being replaced before switching.
        self._stash_position()
        if self.document is not None:
            self.document.close()

        self.document = document
        self.settings.add_recent_file(path)

        target = self.settings.last_page(path) if page is None else page
        self.page = max(0, min(int(target), max(0, document.page_count - 1)))

        self.setWindowTitle(f"{document.display_title} \u2014 Saccade")
        self.page_spin.setRange(1, max(1, document.page_count))
        self.page_total.setText(f"/ {document.page_count}")
        self.sidebar.chapters.set_entries(document.toc)
        self._refresh_bookmarks()
        self._render_page()
        self._update_actions()

        if document.looks_scanned:
            self.sidebar.show_message(
                "This PDF has no text layer \u2014 it looks like a scan.\n\n"
                "Bionic reading needs real text, so run OCR first (for example "
                "`ocrmypdf in.pdf out.pdf`) and open the OCR'd file."
            )
            self.statusBar().showMessage(
                "Scanned PDF: no text layer found, OCR is required", 10000
            )
        return True

    def close_document(self) -> None:
        """Forget the current book and show the welcome page again."""
        self._cancel_search()
        self._stash_position()
        if self.document is not None:
            self.document.close()
            self.document = None
        self.page = 0
        self.setWindowTitle("Saccade")
        self.page_spin.setRange(1, 1)
        self.page_spin.setValue(1)
        self.page_total.setText("/ 0")
        self.sidebar.chapters.set_entries([])
        self.sidebar.bookmarks.set_marks([])
        self.sidebar.show_message("Open a book to search it")
        self._show_welcome()
        self._update_actions()

    def _show_welcome(self) -> None:
        body = bionic.to_html(WELCOME_TEXT, self.settings.intensity,
                              enabled=self.settings.bionic_enabled)
        self.view.show_page(body, heading="Saccade")
        self.status_book.setText("No book open")
        self.status_page.setText("")
        self.status_detail.setText("")
        self.progress.setValue(0)

    def _stash_position(self) -> None:
        if self.document is not None:
            self.settings.set_last_page(self.document.path, self.page)

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def _render_page(self) -> None:
        """Render the current page with the current preferences."""
        if self.document is None:
            return
        body = self._page_html(self.page)
        self.view.show_page(body, heading=self._page_heading())
        self._update_status()
        self.settings.set_last_page(self.document.path, self.page)

    def _use_layout(self) -> bool:
        """True when the page should be shown in its original layout."""
        return (
            self.document is not None
            and self.settings.faithful_layout
            and self.document.has_layout
        )

    def _page_html(self, index: int) -> str:
        """HTML for *index*: the typeset page, or its re-flowed text."""
        assert self.document is not None
        theme = get_theme(self.settings.theme)
        page = self.document.page_layout(index) if self._use_layout() else None
        if page is not None:
            # The reconstructed page carries its own spacing, so the reading
            # line-height must not be stretched over it.
            self.view.set_layout_mode(True)
            self.view.set_column_width(
                page_layout.natural_width(
                    page,
                    base_pt=self.settings.font_size,
                    body_pt=self.document.body_pt,
                    minimum=self.settings.column_width,
                )
            )
            return page_layout.to_html(
                page,
                base_pt=self.settings.font_size,
                body_pt=self.document.body_pt,
                bionic_enabled=self.settings.bionic_enabled,
                intensity=self.settings.intensity,
                ink=theme.ink,
                dark=theme.dark,
            )
        self.view.set_layout_mode(False)
        self.view.set_column_width(self.settings.column_width)
        page = self.document.page_layout(index) if self.document.has_layout else None
        if page is not None and page.spans:
            document = self.document
            view = self.view
            view.clear_images()
            dpr = max(1.0, view.devicePixelRatioF())

            def render_formula(rect, px_per_pt, top, bottom):
                png = document.math_image(
                    index, rect, px_per_pt * dpr, theme.ink, theme.paper, top, bottom
                )
                return view.add_image(png, dpr) if png else None

            if page.is_scan:
                return self._scanned_page_html(page, index, theme, render_formula)
            return page_layout.flow_html(
                page,
                base_pt=self.settings.font_size,
                body_pt=document.body_pt,
                bionic_enabled=self.settings.bionic_enabled,
                intensity=self.settings.intensity,
                math_renderer=render_formula,
            )
        text = self._page_text(index)
        return bionic.to_html(
            text, self.settings.intensity, enabled=self.settings.bionic_enabled
        )

    def _page_text(self, index: int) -> str:
        """Text of *index* in reading order, matching what is on screen."""
        assert self.document is not None
        if self._use_layout():
            return self.document.layout_text(index)
        return self.document.page_text(index)

    def _page_heading(self) -> str:
        """Chapter title (when known) plus the page position."""
        if self.document is None:
            return ""
        parts: list[str] = []
        chapter = self._current_chapter()
        if chapter:
            parts.append(chapter)
        parts.append(f"page {self.page + 1}")
        return " \u00b7 ".join(parts)

    def _current_chapter(self) -> str:
        """Title of the last outline entry at or before the current page."""
        if self.document is None:
            return ""
        title = ""
        for entry in self.document.toc:
            if entry.page <= self.page:
                title = entry.title
            else:
                break
        return title

    def _update_status(self) -> None:
        if self.document is None:
            return
        total = max(1, self.document.page_count)
        percent = (self.page + 1) / total * 100.0
        words = self.document.words_on_page(self.page)

        author = self.document.metadata.get("author") or ""
        self.status_book.setText(
            f"{self.document.display_title}" + (f" \u2014 {author}" if author else "")
        )
        self.status_book.setToolTip(self.document.path)
        self.progress.setValue(int(percent * 10))
        self.status_page.setText(
            f"Page {self.page + 1} / {self.document.page_count}  ({percent:.1f}%)"
        )
        page = self.document.page_layout(self.page) if self.document.has_layout else None
        if page is not None and page.is_scan:
            # Say so plainly: on a scan there is no real text to bolden.
            self.status_detail.setText("scanned page \u00b7 no fixations")
        else:
            self.status_detail.setText(f"{words} words \u00b7 {self.document.backend_name}")
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.page + 1)
        self.page_spin.blockSignals(False)

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #
    def goto_page(self, page: int) -> None:
        """Jump to *page* (0-based), clamped to the document."""
        if self.document is None:
            return
        target = max(0, min(int(page), max(0, self.document.page_count - 1)))
        if target == self.page and self.view.plain_text:
            return
        self.page = target
        self._render_page()
        self.sidebar.chapters.highlight_page(self.page)
        if self.sidebar.results.hits and self.search_term:
            self.sidebar.results.select_page(self.page)
            self.view.highlight_all(self.search_term,
                                    case_sensitive=self.search_case)
            self.view.find_first(self.search_term, case_sensitive=self.search_case)

    def turn_page(self, step: int) -> None:
        """Move *step* pages forward or backward."""
        self.goto_page(self.page + step)

    def goto_last_page(self) -> None:
        if self.document is not None:
            self.goto_page(self.document.page_count - 1)

    def jump_chapter(self, direction: int) -> None:
        """Jump to the start of the next/previous chapter in the outline."""
        if self.document is None or not self.document.toc:
            self.statusBar().showMessage("This PDF has no chapter outline", 4000)
            return
        starts = sorted({entry.page for entry in self.document.toc})
        if direction > 0:
            later = [page for page in starts if page > self.page]
            target = later[0] if later else self.document.page_count - 1
        else:
            earlier = [page for page in starts if page < self.page]
            target = earlier[-1] if earlier else 0
        self.goto_page(target)

    def _on_page_spin(self, value: int) -> None:
        self.goto_page(value - 1)

    def _on_link(self, url) -> None:
        """Follow an internal PDF link (``page:N``) rendered on the page."""
        if url.scheme() == "page" and url.path().isdigit():
            self.goto_page(int(url.path()))

    # ------------------------------------------------------------------ #
    # Preferences
    # ------------------------------------------------------------------ #
    def _scanned_page_html(self, page, index: int, theme, render_formula) -> str:
        """Show a scanned page as the scan itself.

        The text over a scan comes from OCR, which mangles mathematics
        ("x ∈ ℤ" is read as "x E Z"), so a re-flowed transcription would be
        worse than useless in a textbook. The scan still carries its text layer
        underneath, so search keeps working.
        """
        width = max(self.settings.column_width, 320)
        px_per_pt = width / page.width if page.width else 1.0
        rendered = render_formula((0.0, 0.0, page.width, page.height), px_per_pt, 0.0, 0.0)
        if not rendered:
            return page_layout.flow_html(
                page, base_pt=self.settings.font_size, body_pt=self.document.body_pt,
                bionic_enabled=self.settings.bionic_enabled,
                intensity=self.settings.intensity,
            )
        src, shown_width, shown_height = rendered
        self.view.set_column_width(int(shown_width) + 24)
        return (
            f'<p style="margin:0"><img src="{src}" width="{shown_width:.0f}" '
            f'height="{shown_height:.0f}" alt="" /></p>'
        )

    def _apply_reading_settings(self) -> None:
        theme = get_theme(self.settings.theme)
        self.view.configure(
            theme=theme,
            family=self.settings.font_family,
            size_pt=self.settings.font_size,
            line_height=self.settings.line_height,
            justify=self.settings.justify,
            column_width=self.settings.column_width,
            letter_spacing=self.settings.letter_spacing,
            word_spacing=self.settings.word_spacing,
            rerender=not self._use_layout(),
        )
        self.view.set_focus_mode(self.settings.focus_mode)
        for combo in (self.font_combo, self.theme_combo):
            style_combo_popup(combo, theme)
        self.setPalette(self._palette_for(theme))
        # The chrome (toolbar, sidebar, menus, inputs) follows the theme too.
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_qss(theme))
        self.act_justify.setChecked(self.settings.justify)
        self.act_bionic.setChecked(self.settings.bionic_enabled)
        self.act_faithful.setChecked(self.settings.faithful_layout)
        self.act_smart_paragraphs.setChecked(self.settings.smart_paragraphs)

    @staticmethod
    def _palette_for(theme):
        """Window palette matching the reading theme."""
        from PyQt6.QtGui import QColor, QPalette

        palette = QApplication.style().standardPalette()
        if not theme.dark:
            return palette
        base = QColor("#1B1E23")
        paper = QColor(theme.paper)
        ink = QColor(theme.ink)
        palette.setColor(QPalette.ColorRole.Window, base)
        palette.setColor(QPalette.ColorRole.WindowText, ink)
        palette.setColor(QPalette.ColorRole.Base, paper)
        palette.setColor(QPalette.ColorRole.Text, ink)
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#23262C"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#23262C"))
        palette.setColor(QPalette.ColorRole.ButtonText, ink)
        palette.setColor(QPalette.ColorRole.ToolTipBase, paper)
        palette.setColor(QPalette.ColorRole.ToolTipText, ink)
        palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, base)
        return palette

    def toggle_bionic(self) -> None:
        self.settings.bionic_enabled = self.act_bionic.isChecked()
        self._render_page()

    def toggle_justify(self) -> None:
        self.settings.justify = self.act_justify.isChecked()
        self._apply_reading_settings()
        self._render_page()

    def toggle_smart_paragraphs(self) -> None:
        self.settings.smart_paragraphs = self.act_smart_paragraphs.isChecked()
        if self.document is not None:
            self.document.set_smart_paragraphs(self.settings.smart_paragraphs)
        self._render_page()

    def toggle_faithful(self) -> None:
        """Switch between the typeset page and re-flowed text."""
        self.settings.faithful_layout = self.act_faithful.isChecked()
        if self.document is not None and not self.document.has_layout:
            self.statusBar().showMessage(
                "This book has no text geometry, so it is shown as re-flowed text",
                5000,
            )
        self._apply_reading_settings()
        self._render_page()
        self._refresh_bookmarks()

    def set_theme(self, key: str) -> None:
        self.settings.theme = key
        action = self.theme_actions.get(key)
        if action is not None:
            action.setChecked(True)
        index = self.theme_combo.findData(key)
        if index >= 0 and index != self.theme_combo.currentIndex():
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
        self._apply_reading_settings()
        self._render_page()

    def _on_theme_combo(self, index: int) -> None:
        key = self.theme_combo.itemData(index)
        if key:
            self.set_theme(str(key))

    def _on_font_family(self, family: str) -> None:
        if not family:
            return
        self.settings.font_family = family
        self._apply_reading_settings()
        self._render_page()

    def _on_font_size(self, size: int) -> None:
        self.settings.font_size = size
        self._apply_reading_settings()
        self._render_page()

    def zoom(self, step: int) -> None:
        self.size_spin.setValue(self.settings.font_size + step)

    def reset_zoom(self) -> None:
        from ..settings import DEFAULT_FONT_SIZE

        self.size_spin.setValue(DEFAULT_FONT_SIZE)

    def adjust_line_height(self, delta: float) -> None:
        self.settings.line_height = round(self.settings.line_height + delta, 2)
        self._apply_reading_settings()
        self._render_page()
        self.statusBar().showMessage(f"Line spacing {self.settings.line_height:.2f}", 3000)

    def adjust_letter_spacing(self, delta: float) -> None:
        self.settings.letter_spacing = round(self.settings.letter_spacing + delta, 2)
        self._apply_reading_settings()
        self._render_page()
        self.statusBar().showMessage(
            f"Letter spacing {self.settings.letter_spacing:.1f} px", 3000
        )

    def adjust_word_spacing(self, delta: float) -> None:
        self.settings.word_spacing = round(self.settings.word_spacing + delta, 2)
        self._apply_reading_settings()
        self._render_page()
        self.statusBar().showMessage(
            f"Word spacing {self.settings.word_spacing:.1f} px", 3000
        )

    def toggle_focus_mode(self) -> None:
        """Dim everything but the paragraph being read."""
        enabled = self.act_focus.isChecked()
        self.settings.focus_mode = enabled
        self.view.set_focus_mode(enabled)
        self.statusBar().showMessage(
            "Focus mode on: the paragraph under the pointer stays bright (F2)"
            if enabled else "Focus mode off",
            4000,
        )

    def apply_comfort_preset(self) -> None:
        """One click to the settings that suit most readers who find dense
        pages hard: bigger text, a short line, generous spacing, a warm page
        and focus mode."""
        s = self.settings
        accessible = installed_accessible_fonts()
        if accessible:
            s.font_family = accessible[0]
        s.font_size = max(s.font_size, 17)
        s.line_height = 1.8
        s.letter_spacing = 1.0
        s.word_spacing = 3.0
        s.column_width = 620
        s.justify = False
        s.theme = "sepia"
        s.bionic_enabled = True
        s.focus_mode = True
        self._sync_controls()
        self._apply_reading_settings()
        self._render_page()
        note = "" if accessible else "  (install a dyslexia font: Help → Reading fonts)"
        self.statusBar().showMessage("Easy-reading setup applied" + note, 6000)

    def reset_reading_settings(self) -> None:
        """Back to the out-of-the-box reading settings."""
        s = self.settings
        s.font_family = DEFAULT_FONT_FAMILY
        s.font_size = DEFAULT_FONT_SIZE
        s.line_height = DEFAULT_LINE_HEIGHT
        s.letter_spacing = 0.0
        s.word_spacing = 0.0
        s.column_width = DEFAULT_COLUMN_WIDTH
        s.theme = DEFAULT_THEME
        s.focus_mode = False
        self._sync_controls()
        self._apply_reading_settings()
        self._render_page()
        self.statusBar().showMessage("Reading settings reset", 4000)

    def _sync_controls(self) -> None:
        """Push the current settings back onto the toolbar and menu widgets."""
        s = self.settings
        for widget, value in (
            (self.font_combo, s.font_family),
            (self.size_spin, s.font_size),
            (self.intensity_slider, int(s.intensity * 100)),
        ):
            widget.blockSignals(True)
            if widget is self.font_combo:
                if widget.findText(value) < 0:
                    widget.addItem(value)
                widget.setCurrentText(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(s.theme)))
        self.theme_combo.blockSignals(False)
        action = self.theme_actions.get(s.theme)
        if action is not None:
            action.setChecked(True)
        self.act_focus.setChecked(s.focus_mode)
        self.act_bionic.setChecked(s.bionic_enabled)
        self.act_justify.setChecked(s.justify)
        self.intensity_label.setText(f"{int(s.intensity * 100)}%")

    def adjust_column(self, delta: int) -> None:
        self.settings.column_width = max(
            380, min(1400, self.settings.column_width + delta)
        )
        self._apply_reading_settings()
        self.statusBar().showMessage(
            f"Text column width {self.settings.column_width} px", 3000
        )

    def _on_intensity(self, value: int) -> None:
        self.intensity_label.setText(f"{value}%")
        self.settings.intensity = value / 100.0
        self._render_page()

    # ------------------------------------------------------------------ #
    # Searching
    # ------------------------------------------------------------------ #
    @property
    def search_term(self) -> str:
        return self.find_edit.text().strip()

    @property
    def search_case(self) -> bool:
        return self.act_find_case.isChecked()

    def focus_search(self) -> None:
        """Put the cursor in the search field."""
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _on_find_text_changed(self, text: str) -> None:
        """Live-highlight the term on the current page as it is typed."""
        self.view.highlight_all(text.strip(), case_sensitive=self.search_case)

    def start_search(self) -> None:
        """Search the whole book in a background thread."""
        term = self.search_term
        self._cancel_search()
        if self.document is None:
            self.statusBar().showMessage("Open a book first", 3000)
            return
        if not term:
            self.sidebar.show_message("Type something to search for")
            return

        self.view.highlight_all(term, case_sensitive=self.search_case)
        self.statusBar().showMessage(f"Searching for \u201c{term}\u201d\u2026")
        worker = SearchWorker(
            self.document, term,
            case_sensitive=self.search_case,
            start_page=self.page,
            parent=self,
        )
        worker.progress.connect(self._on_search_progress)
        worker.hits_found.connect(lambda hits, q=term: self._on_hits_found(hits, q))
        worker.finished.connect(self._on_search_finished)
        self._search_worker = worker
        worker.start()

    def restart_search(self) -> None:
        """Re-run the current search (used when the case option changes)."""
        if self.search_term:
            self.start_search()

    def _cancel_search(self) -> None:
        worker = self._search_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(2000)
        self._search_worker = None

    def _on_search_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Searching\u2026 {done}/{total} pages")

    def _on_search_finished(self) -> None:
        self._search_worker = None

    def _on_hits_found(self, hits: list[SearchHit], query: str) -> None:
        self.sidebar.show_results(hits)
        if not hits:
            self.statusBar().showMessage(f"No matches for \u201c{query}\u201d", 5000)
            return
        self.statusBar().showMessage(
            f"{len(hits)} match{'es' if len(hits) != 1 else ''} for \u201c{query}\u201d",
            6000,
        )
        first = hits[0]
        if first.page != self.page:
            self.goto_page(first.page)
        else:
            self.view.highlight_all(query, case_sensitive=self.search_case)
            self.view.find_first(query, case_sensitive=self.search_case)

    def goto_search_hit(self, direction: int) -> None:
        """Select the next/previous search result and jump to it."""
        if self.document is None:
            return
        if not self.sidebar.results.hits:
            if self.search_term:
                self.start_search()
            else:
                self.statusBar().showMessage("No search results (Ctrl+F to search)", 3000)
            return
        next_index = self.sidebar.results.current_index + direction
        hit = self.sidebar.results.select_index(next_index)
        if hit is None:
            return
        self.goto_page(hit.page)
        self.view.highlight_all(self.search_term, case_sensitive=self.search_case)
        self.view.find_first(self.search_term, case_sensitive=self.search_case)

    def show_results_panel(self) -> None:
        self.sidebar.show_results(self.sidebar.results.hits)

    def show_chapters(self) -> None:
        self.sidebar.show_chapters()

    # ------------------------------------------------------------------ #
    # Bookmarks
    # ------------------------------------------------------------------ #
    def add_bookmark(self) -> None:
        """Bookmark the current page, labelled with its first line of text."""
        if self.document is None:
            self.statusBar().showMessage("Open a book first", 3000)
            return
        self.settings.add_bookmark(
            self.document.path, self.page, self._bookmark_label(self.page)
        )
        self._refresh_bookmarks()
        self.sidebar.show_bookmarks()
        self.statusBar().showMessage(f"Bookmarked page {self.page + 1}", 4000)

    def remove_bookmark(self, page: int) -> None:
        """Remove the bookmark of *page*."""
        if self.document is None:
            return
        self.settings.remove_bookmark(self.document.path, page)
        self._refresh_bookmarks()
        self.statusBar().showMessage(f"Removed bookmark for page {page + 1}", 4000)

    def remove_current_bookmark(self) -> None:
        self.remove_bookmark(self.page)

    def _refresh_bookmarks(self) -> None:
        marks = self.settings.bookmarks(self.document.path) if self.document else []
        self.sidebar.bookmarks.set_marks(marks)

    def _bookmark_label(self, page: int) -> str:
        """Short label for a bookmark: the first readable line of the page."""
        if self.document is None:
            return ""
        text = self.document.page_text(page)
        for line in text.split("\n"):
            candidate = " ".join(line.split())
            if len(candidate) >= 3 and not candidate.isdigit():
                return candidate[:70]
        return ""

    # ------------------------------------------------------------------ #
    # Panes and window state
    # ------------------------------------------------------------------ #
    def toggle_sidebar(self) -> None:
        visible = self.act_sidebar.isChecked()
        self.dock.setVisible(visible)
        self.settings.sidebar_visible = visible

    def toggle_zen(self) -> None:
        """Hide every distraction; press F11 again to come back."""
        self._zen = not self._zen
        for widget in (self.toolbar, self.dock, self.statusBar()):
            widget.setVisible(not self._zen)
        if self._zen:
            self.act_sidebar.setChecked(False)
            self.showFullScreen()
            self.statusBar().showMessage("Zen mode \u2014 press F11 to exit")
        else:
            self.act_sidebar.setChecked(self.settings.sidebar_visible)
            self.dock.setVisible(self.settings.sidebar_visible)
            self.showNormal()
        self.view.setFocus()

    def _restore_window_state(self) -> None:
        geometry = self.settings.window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1100, 780)
        state = self.settings.window_state()
        if state is not None:
            self.restoreState(state)
        self.dock.setVisible(self.settings.sidebar_visible)
        self.act_sidebar.setChecked(self.settings.sidebar_visible)

    def _save_window_state(self) -> None:
        self.settings.set_window_geometry(self.saveGeometry())
        self.settings.set_window_state(self.saveState())
        self.settings.sidebar_visible = self.dock.isVisible()
        self._stash_position()
        self.settings.sync()

    def _clear_recent(self) -> None:
        self.settings.clear_recent_files()
        self.statusBar().showMessage("Recent books list cleared", 3000)

    def _update_actions(self) -> None:
        """Enable navigation only while a book is open."""
        has_book = self.document is not None
        for action in (
            self.act_close, self.act_prev, self.act_next, self.act_prev_pg,
            self.act_next_pg, self.act_first, self.act_last, self.act_next_chapter,
            self.act_prev_chapter, self.act_bookmark_add, self.act_bookmark_remove,
            self.act_find, self.act_search, self.act_copy_page, self.act_copy_bionic,
        ):
            action.setEnabled(has_book)
        self.page_spin.setEnabled(has_book)

    # ------------------------------------------------------------------ #
    # Clipboard
    # ------------------------------------------------------------------ #
    def copy_page_text(self) -> None:
        """Copy the current page as plain text."""
        if self.document is None:
            return
        text = self.document.page_text(self.page)
        self._to_clipboard(text, "page text")

    def copy_bionic_text(self) -> None:
        """Copy the current page as plain text with visible fixation markers.

        Useful for pasting into a plain-text editor, where there is no bold.
        """
        if self.document is None:
            return
        marked = bionic.to_marked(
            self.document.page_text(self.page),
            self.settings.intensity,
            enabled=self.settings.bionic_enabled,
        )
        self._to_clipboard(marked, "page text with fixation markers")

    def _to_clipboard(self, text: str, what: str) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {what} ({len(text)} characters)", 4000)

    # ------------------------------------------------------------------ #
    # Drag and drop
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_pdf(urls) -> str | None:
        for url in urls:
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path.lower().endswith(".pdf") and os.path.isfile(path):
                return path
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._first_pdf(event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        path = self._first_pdf(event.mimeData().urls())
        if path:
            event.acceptProposedAction()
            self.open_path(path)

    # ------------------------------------------------------------------ #
    # Dialogs
    # ------------------------------------------------------------------ #
    def show_backends(self) -> None:
        """Explain which text engines are available."""
        from ..document import backend_names, available_backends

        available = available_backends()
        lines = ["PDF text engines, in order of preference:\n"]
        for name in backend_names():
            mark = "\u2713" if name in available else "\u2717"
            lines.append(f"  {mark}  {name}")
        lines.append("\nOnly the first available engine is used. Force one with the")
        lines.append("SACCADE_BACKEND environment variable, for example:")
        lines.append("    SACCADE_BACKEND=pypdf saccade book.pdf")
        QMessageBox.information(self, "Text engines", "\n".join(lines))

    def show_reading_fonts(self) -> None:
        """Which easier-reading fonts are installed, and how to get the rest."""
        installed = installed_accessible_fonts()
        lines = ["Fonts designed to be easier to read (wide, unambiguous letters):\n"]
        if installed:
            lines += [f"  ✓  {name}" for name in installed]
            lines.append("\nThey are listed first in the toolbar's font box.")
        else:
            lines.append("  None of them are installed yet.")
        lines.append("\nTo install:")
        lines += [f"  {name}\n      {how}" for name, how in FONT_PACKAGES]
        lines.append("\nAfter installing, restart Saccade to see them.")
        QMessageBox.information(self, "Reading fonts", "\n".join(lines))

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "Reading\n"
            "  Space / Down        scroll, then go to the next page\n"
            "  Up / Backspace      scroll up, then go to the previous page\n"
            "  N / PgDown          next page\n"
            "  B / PgUp            previous page\n"
            "  Ctrl+Down / Up      next / previous chapter\n"
            "  Ctrl+Home / End     first / last page\n"
            "  Ctrl+D              bookmark this page\n"
            "  Ctrl+Shift+D        remove this page's bookmark\n\n"
            "Look and feel\n"
            "  F2                  focus mode (dim all but this paragraph)\n"
            "  Ctrl+B              bionic fixations on/off\n"
            "  Ctrl+L              keep the page layout on/off\n"
            "  Ctrl+= / Ctrl+-     bigger / smaller text\n"
            "  Ctrl+0              normal text size\n"
            "  Ctrl+Alt+= / -      wider / tighter letter spacing\n"
            "  Ctrl+Shift+= / -    wider / narrower text column\n"
            "  Ctrl+wheel          bigger / smaller text\n"
            "  F4 / F5 / F9        chapters / results / library panel\n"
            "  F11                 zen mode (text only)\n\n"
            "Search\n"
            "  Ctrl+F              focus the search field, Return searches\n"
            "  F3 / Shift+F3       next / previous result\n\n"
            "  Ctrl+O / Ctrl+W     open / close a book\n"
            "  Ctrl+Q              quit",
        )

    def show_about(self) -> None:
        """Open the modern About dialog (support cards, logos, repo link)."""
        from .about_dialog import AboutDialog

        AboutDialog(self).exec()

    def open_repo(self) -> None:
        """Open the project's source repository in the browser."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        from ..support import REPO_URL

        QDesktopServices.openUrl(QUrl(REPO_URL))

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._cancel_search()
        self._save_window_state()
        if self.document is not None:
            self.document.close()
            self.document = None
        super().closeEvent(event)
