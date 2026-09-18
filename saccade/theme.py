"""Colour themes and the CSS used by the reading view.

Qt's rich-text engine understands only a small subset of CSS, so the stylesheet
below sticks to properties ``QTextDocument`` really supports (``color``,
``font-family``, ``font-size``, ``margin``, ``text-align``) and sets the block
line spacing programmatically where needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QListView, QWidget

__all__ = [
    "THEMES", "Theme", "available_themes", "get_theme",
    "PopupCornerFix", "install_popup_corner_fix", "style_combo_popup",
]


@dataclass(frozen=True)
class Theme:
    """A reading colour scheme.

    ``paper`` is the page background, ``ink`` the body text, ``dim`` the
    secondary text (page numbers, progress) and ``accent`` the highlight colour.
    """

    key: str
    label: str
    paper: str
    ink: str
    dim: str
    accent: str
    #: Whether Qt widgets should use a dark palette.
    dark: bool = False

    def document_css(self, *, family: str, size_pt: int, line_height: float,
                     justify: bool, margin_pt: int = 0) -> str:
        """CSS for the reading view's document (colours, font, spacing)."""
        return f"""
            body {{
                color: {self.ink};
                background-color: {self.paper};
                font-family: "{family}";
                font-size: {size_pt}pt;
                margin: {margin_pt}px;
            }}
            p {{
                margin-top: 0;
                margin-bottom: {max(4, int(size_pt * (line_height - 1) + 6))}px;
                text-align: {"justify" if justify else "left"};
            }}
            b {{ color: {self.ink}; }}
            a {{ color: {self.accent}; text-decoration: none; }}
            hr {{ color: {self.dim}; }}
            .pageinfo {{ color: {self.dim}; font-size: {max(8, size_pt - 3)}pt; }}
            /* Structure mode: bands sit side by side in tables, so no padding,
               no borders and no wrapping between cells. */
            table {{ border-collapse: collapse; }}
            td {{ padding: 0; border: none; }}
            img {{ border: none; }}
        """


#: Reading themes, light first (the default for long reading sessions).
THEMES: dict[str, Theme] = {
    "paper": Theme("paper", "Paper", "#FBF7EF", "#2B2B2B", "#8A8377", "#B07D3A"),
    "white": Theme("white", "White", "#FFFFFF", "#1B1B1B", "#8C8C8C", "#2F6FAF"),
    "sepia": Theme("sepia", "Sepia", "#F4ECD8", "#3B3021", "#8C7B5F", "#A0662F"),
    "night": Theme("night", "Night", "#14161A", "#D7D3CC", "#7A7F87", "#E0A458", dark=True),
    "grey": Theme("grey", "Grey", "#2A2C31", "#D2D6DB", "#8B9199", "#7FB3D5", dark=True),
}

DEFAULT_THEME = "paper"


def available_themes() -> list[Theme]:
    """Themes in a stable, display-friendly order."""
    return list(THEMES.values())


def get_theme(key: str) -> Theme:
    """Look up a theme by key, falling back to the default."""
    return THEMES.get(key, THEMES[DEFAULT_THEME])


# --------------------------------------------------------------------------- #
# Application chrome (the modern Qt stylesheet)
# --------------------------------------------------------------------------- #

def _rgba(hex_color: str, alpha: float) -> str:
    """``#RRGGBB`` -> Qt stylesheet ``rgba(...)`` string."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _on_accent(hex_color: str) -> str:
    """A readable text colour to put on top of *hex_color*."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "#14161A" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


def _shade(hex_color: str, factor: float) -> str:
    """Lighten (``factor > 1``) or darken (``factor < 1``) a ``#RRGGBB`` colour."""
    value = hex_color.lstrip("#")
    parts = (min(255, max(0, round(int(value[i:i + 2], 16) * factor)))
             for i in (0, 2, 4))
    return "#" + "".join(f"{p:02X}" for p in parts)


def _chrome_colours(theme: Theme) -> dict[str, str]:
    """Colours for the application chrome, derived from the reading theme."""
    if theme.dark:
        c = {
            "window": "#17191E", "card": "#1F2228", "hover": "#262A32",
            "border": "#2C313A", "text": "#D7D3CC", "dim": "#8B9199",
        }
    else:
        c = {
            "window": "#F3F1EC", "card": "#FFFFFF", "hover": "#E9E5DC",
            "border": "#DFD9CC", "text": "#2B2B2B", "dim": "#8A8377",
        }
    accent = theme.accent
    return {
        **c,
        "accent": accent,
        "accent_soft": _rgba(accent, 0.16),
        "accent_hover": _shade(accent, 0.85 if not theme.dark else 1.18),
        "on_accent": _on_accent(accent),
    }


def app_qss(theme: Theme) -> str:
    """A modern, flat stylesheet for the whole application chrome.

    The reading page keeps its own paper colour via the document CSS; this
    stylesheet styles everything around it (toolbar, sidebar, menus, inputs,
    scrollbars, dialogs).  It is derived from the theme, so switching themes
    restyles the chrome too.
    """
    subs = _chrome_colours(theme)
    return """
        * {{ outline: none; }}
        QWidget {{
            font-family: 'Adwaita Sans', 'Noto Sans', 'DejaVu Sans', sans-serif;
            font-size: 10pt;
            color: {text};
        }}
        QMainWindow, QDialog {{ background-color: {window}; }}
        QLabel {{ background: transparent; }}

        QMenuBar {{ background: {window}; border: none; padding: 2px 4px; }}
        QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; background: transparent; }}
        QMenuBar::item:selected {{ background: {hover}; }}
        QMenu {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 10px; padding: 6px;
        }}
        QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; background: transparent; }}
        QMenu::item:selected {{ background: {accent_soft}; color: {accent}; }}
        QMenu::item:disabled {{ color: {dim}; }}
        QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}

        QToolBar {{ background: {window}; border: none; padding: 5px 10px; spacing: 6px; }}
        QToolBar::separator {{ width: 1px; background: {border}; margin: 6px 4px; }}
        QToolButton {{
            background: transparent; color: {text}; border: none;
            border-radius: 8px; padding: 6px 11px;
        }}
        QToolButton:hover {{ background: {hover}; }}
        QToolButton:pressed {{ background: {border}; }}
        QToolButton:checked {{ background: {accent_soft}; color: {accent}; font-weight: 600; }}
        QToolButton:disabled {{ color: {dim}; }}

        QLineEdit, QSpinBox, QComboBox {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 8px; padding: 5px 10px;
            selection-background-color: {accent}; selection-color: {on_accent};
        }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
        QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {dim}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        /* The drop-down list is a QComboBoxListView inside its own popup
           window; a "QComboBox QAbstractItemView" selector never reaches it,
           so both classes are named directly. Without this the list keeps the
           system's square frame and blue selection bar. */
        QComboBoxPrivateContainer {{ background: transparent; border: none; }}
        QComboBox QAbstractItemView, QComboBoxListView {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 10px; padding: 4px;
            selection-background-color: {accent_soft}; selection-color: {accent};
            outline: 0;
        }}
        /* A scroll area paints its background on the viewport, which knows
           nothing about border-radius: left opaque it shows as square corners
           behind the rounded frame. */
        QComboBoxListView > QWidget#qt_scrollarea_viewport {{
            background: transparent;
        }}
        QComboBoxListView::item {{
            padding: 5px 10px; border-radius: 6px; min-height: 20px;
        }}
        QComboBoxListView::item:hover {{ background: {hover}; }}
        QComboBoxListView::item:selected {{
            background: {accent_soft}; color: {accent};
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 16px; border: none; background: transparent; border-radius: 4px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {hover}; }}

        /* ---- buttons ---- */
        QPushButton {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 8px;
            padding: 6px 16px; min-width: 64px;
        }}
        QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
        QPushButton:pressed {{ background: {border}; }}
        QPushButton:default {{
            background: {accent}; color: {on_accent};
            border-color: {accent}; font-weight: 600;
        }}
        QPushButton:default:hover {{ background: {accent_hover}; }}
        QPushButton:disabled {{ color: {dim}; border-color: {border}; }}
        QPushButton#copyBtn {{
            background: transparent; color: {dim};
            border: 1px solid {border}; border-radius: 7px;
            padding: 3px 10px; min-width: 0px; font-size: 9pt;
        }}
        QPushButton#copyBtn:hover {{ color: {accent}; border-color: {accent}; }}

        /* ---- tabs, lists, trees ---- */
        QTabWidget::pane {{ border: none; }}
        QTabBar {{ qproperty-drawBase: 0; }}
        QTabBar::tab {{
            background: transparent; color: {dim};
            padding: 6px 14px; margin-right: 2px; border-radius: 8px;
        }}
        QTabBar::tab:selected {{ background: {accent_soft}; color: {accent}; font-weight: 600; }}
        QTabBar::tab:hover:!selected {{ color: {text}; background: {hover}; }}
        QTreeWidget, QListWidget {{
            background: transparent; border: none; color: {text}; outline: 0;
        }}
        QTreeWidget::item, QListWidget::item {{ padding: 4px 6px; border-radius: 6px; }}
        QTreeWidget::item:hover, QListWidget::item:hover {{ background: {hover}; }}
        QTreeWidget::item:selected, QListWidget::item:selected {{
            background: {accent_soft}; color: {accent};
        }}
        QHeaderView {{ background: {window}; border: none; }}
        QHeaderView::section {{
            background: transparent; color: {dim}; border: none;
            border-bottom: 1px solid {border}; padding: 4px 6px;
        }}

        /* ---- thin modern scrollbars ---- */
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
        QScrollBar::handle:vertical:hover {{ background: {dim}; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}
        QScrollBar::handle:horizontal:hover {{ background: {dim}; }}
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: none; border: none; width: 0; height: 0;
        }}

        /* ---- dock, status, progress ---- */
        QDockWidget {{ color: {text}; }}
        QDockWidget::title {{ background: {window}; padding: 6px 8px 2px 8px; }}
        QStatusBar {{ background: {window}; border-top: 1px solid {border}; }}
        QStatusBar QLabel {{ color: {dim}; padding: 0 6px; }}
        QStatusBar::item {{ border: none; }}
        QProgressBar {{
            background: {card}; border: 1px solid {border};
            border-radius: 5px; height: 10px;
        }}
        QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}

        /* ---- cards (About dialog) ---- */
        QFrame#card {{
            background: {card}; border: 1px solid {border}; border-radius: 10px;
        }}
        QFrame#card:hover {{ border-color: {accent}; }}
        QLabel#repoLink {{ color: {accent}; }}

        /* ---- slider ---- */
        QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
        QSlider::handle:horizontal {{
            width: 14px; height: 14px; margin: -5px 0;
            border-radius: 7px; background: {card}; border: 2px solid {accent};
        }}
        QSlider::handle:horizontal:hover {{ background: {accent}; }}

        /* ---- tooltips ---- */
        QToolTip {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 6px; padding: 5px 8px;
        }}
    """.format(**subs)


# --------------------------------------------------------------------------- #
# Popup corner fix
# --------------------------------------------------------------------------- #
#
# QMenu and the QComboBox drop-down list are both borderless top-level windows
# (Qt.WindowType.Popup).  app_qss rounds their corners with ``border-radius``,
# but a plain top-level window is still backed by an opaque, rectangular
# surface, so the window manager paints a small square patch of that
# background in each corner instead of letting it show through -- the "rough
# edges" on every dropdown and menu.  Giving the popup an alpha-capable
# backing surface (``WA_TranslucentBackground``) lets the corners outside the
# rounded rectangle blend away instead.


class PopupCornerFix(QObject):
    """App-wide filter that makes every popup window (menus, combo boxes)
    render with clean rounded corners instead of square window-manager
    backing edges."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override name)
        # windowType() is the *masked* window type; a raw ``flags & Popup``
        # bitwise test is wrong here -- Qt.WindowType.Popup is a composite of
        # several bits (it includes the plain Window bit), so that check is
        # truthy for every top-level widget, not just popups. That bug once
        # made the whole main window translucent instead of just dropdowns.
        if (
            event.type() == QEvent.Type.Polish
            and isinstance(obj, QWidget)
            and obj.windowType() == Qt.WindowType.Popup
        ):
            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        return False


def style_combo_popup(combo, theme: Theme) -> None:
    """Give a combo box's drop-down list the app's own look.

    Its list lives in a private popup window that app-wide selectors do not
    reach, so the rules are set on the widget itself: without this the list
    keeps the desktop's square frame and blue selection bar. The viewport is
    made transparent because a scroll area paints its background there, and
    that paint ignores ``border-radius`` -- the square corner behind the
    rounded frame.
    """
    colours = _chrome_colours(theme)
    view = combo.view()
    if view.metaObject().className() != "QListView":
        # A combo box's own list paints its rows with a private delegate that
        # ignores "::item" rules, so it keeps the desktop's blue selection bar.
        # A plain list view is drawn by the normal delegate, which obeys them.
        view = QListView(combo)
        combo.setView(view)
    view.setStyleSheet(
        """
        QAbstractItemView {{
            background: {card}; color: {text};
            border: 1px solid {border}; border-radius: 10px; padding: 4px;
            outline: 0;
        }}
        QAbstractItemView::item {{ padding: 5px 10px; border-radius: 6px; }}
        QAbstractItemView::item:hover {{ background: {hover}; }}
        QAbstractItemView::item:selected {{ background: {accent_soft}; color: {accent}; }}
        """.format(**colours)
    )
    view.viewport().setStyleSheet("background: transparent;")
    view.viewport().setAutoFillBackground(False)
    # The current row is painted from the palette, not the stylesheet, so the
    # palette has to carry the same soft accent.
    palette = view.palette()
    highlight = QColor(theme.accent)
    highlight.setAlphaF(0.22)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.accent))
    view.setPalette(palette)
    window = view.window()
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setStyleSheet("background: transparent;")


def install_popup_corner_fix(app) -> PopupCornerFix:
    """Install :class:`PopupCornerFix` on *app* and return it.

    The caller must keep a reference (or parent it to *app*, as this does) --
    an event filter stops working once the ``QObject`` behind it is garbage
    collected.
    """
    fix = PopupCornerFix(app)
    app.installEventFilter(fix)
    return fix