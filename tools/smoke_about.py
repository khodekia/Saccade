"""Headless check that the modern About dialog (logos + wallets) builds."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

from saccade.support import (
    REPO_LABEL,
    REPO_URL,
    WALLETS,
    app_icon_path,
    wallet_icon_path,
    wallets_html,
    wallets_markdown,
)

# 1. wallet data integrity
assert len(WALLETS) == 5, f"expected 5 wallets, got {len(WALLETS)}"
html_block = wallets_html()
md_block = wallets_markdown()
for _key, label, _net, addr in WALLETS:
    assert addr in html_block, f"{addr!r} missing from HTML"
    assert addr in md_block, f"{addr!r} missing from Markdown"
print(f"support data OK: {len(WALLETS)} wallets present in HTML + Markdown")

# 2. every bundled logo and the app icon exist
missing = [key for key, *_ in WALLETS if not wallet_icon_path(key)]
assert not missing, f"missing wallet logos: {missing}"
assert app_icon_path(), "missing app icon"
print("assets OK: app icon + 5 wallet logos bundled")

# 3. the real About dialog constructs and exposes everything
app = QApplication(sys.argv)
from PyQt6.QtWidgets import QLabel

from saccade.ui.about_dialog import AboutDialog

dialog = AboutDialog()
assert dialog.windowTitle() == "About Saccade"
text = " \n ".join(
    label.text() for label in dialog.findChildren(QLabel)
)
for _key, _label, _net, addr in WALLETS:
    assert addr in text, f"{addr!r} not visible in the dialog"
assert REPO_URL in text and REPO_LABEL in text, "repo link missing"
assert len(dialog.wallet_addresses) == 5
dialog.close()
print("About dialog OK: version, 5 logo'd wallet cards, repo link")
print("ABOUT_SMOKE_OK")

