"""Modern About dialog: app info, donation cards with logos, repo link."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .. import __version__
from ..support import (
    REPO_LABEL,
    REPO_URL,
    WALLETS,
    app_icon_path,
    wallet_icon_path,
)

__all__ = ["AboutDialog"]

MONO_FAMILY = "DejaVu Sans Mono"


class AboutDialog(QDialog):
    """About Saccade: description, support cards and the project link."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Saccade")
        self.setModal(True)
        self.setMinimumWidth(480)

        # Kept for tests / programmatic inspection.
        self.wallet_addresses = [addr for _k, _l, _n, addr in WALLETS]

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 16)
        root.setSpacing(9)
        # Wrapped text is measured after the width is known, so without this
        # the dialog opens too short and clips its own first paragraph.
        root.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        # -- header ------------------------------------------------------ #
        header = QHBoxLayout()
        icon = QLabel()
        icon_path = app_icon_path()
        if icon_path:
            icon.setPixmap(QIcon(icon_path).pixmap(54, 54))
        icon.setFixedSize(54, 54)
        header.addWidget(icon)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel(f"<h2 style='margin:0'>Saccade"
                      f"<span style='color:#8a8f98; font-size:12pt'>"
                      f" {__version__}</span></h2>")
        tagline = QLabel("A kinder way to read PDFs on Linux.")
        tagline.setWordWrap(True)
        titles.addWidget(name)
        titles.addWidget(tagline)
        header.addLayout(titles, 1)
        root.addLayout(header)

        about = QLabel(
            "Some of us lose the line halfway through a paragraph, or read it "
            "three times and take nothing in. Saccade bolds the start of every "
            "word to give your eye something to hold on to, and dims "
            "everything but the paragraph you are on.<br><br>"
            "It is named after <i>saccades</i>: the small, quick jumps your "
            "eyes make as you read. Maths gets particular care — formulas "
            "appear exactly as the book prints them, fraction bars and all."
        )
        about.setWordWrap(True)
        # A wrapped label is measured at its own sizeHint width, which is
        # wider than the dialog: without this the text is clipped on opening.
        about.setMinimumHeight(about.heightForWidth(self.minimumWidth() - 52))
        root.addWidget(about)

        # -- support cards ------------------------------------------------ #
        heading = QLabel("<b>If it helps you, you can buy me a coffee</b>")
        heading.setContentsMargins(0, 4, 0, 0)
        root.addWidget(heading)

        # The wallets are a short, fixed list, so they are laid out directly.
        # Inside a scroll area they ended up cramped: a scroll bar over the
        # Copy buttons, and the last card cut in half.
        for key, label, net, addr in WALLETS:
            root.addWidget(self._wallet_card(key, label, net, addr))
        root.addSpacing(4)

        # -- footer ------------------------------------------------------- #
        repo = QLabel(f"Source code &amp; issues: "
                      f"<a href='{REPO_URL}'>{REPO_LABEL}</a>")
        repo.setObjectName("repoLink")
        repo.setOpenExternalLinks(True)
        root.addWidget(repo)

        license_note = QLabel("Free and open source under the MIT licence \u00b7 "
                              "the bionic-reading idea was popularised by "
                              "Renato Casutt")
        license_note.setWordWrap(True)
        license_note.setStyleSheet("color: #8a8f98; font-size: 9pt;")
        root.addWidget(license_note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ------------------------------------------------------------------ #
    def _wallet_card(self, key: str, label: str, net: str, addr: str) -> QFrame:
        """One donation row: logo, name/network, selectable address, copy."""
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)

        logo = QLabel()
        icon_path = wallet_icon_path(key)
        if icon_path:
            logo.setPixmap(QIcon(icon_path).pixmap(24, 24))
        logo.setFixedSize(24, 24)
        layout.addWidget(logo)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name = QLabel(f"<b>{label}</b>"
                      f"<span style='color:#8a8f98'> \u00b7 {net}</span>")
        address = QLabel(addr)
        address.setFont(QFont(MONO_FAMILY, 9))
        address.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        address.setToolTip("Click to select, Ctrl+C to copy")
        text_col.addWidget(name)
        text_col.addWidget(address)
        layout.addLayout(text_col, 1)

        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("copyBtn")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(
            lambda _=False, b=copy_btn, a=addr: self._copy(b, a))
        layout.addWidget(copy_btn)
        return card

    def _copy(self, button: QPushButton, address: str) -> None:
        """Copy *address* to the clipboard and flash the button label."""
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(address)
        old = button.text()
        button.setText("Copied \u2713")
        QTimer.singleShot(1600, lambda: button.setText(old))
