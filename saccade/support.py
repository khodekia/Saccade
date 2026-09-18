"""Project support / donation information.

Kept in one module so the About dialog, the README and any packaging
metadata stay in sync.
"""

from __future__ import annotations

import html
import os

__all__ = [
    "REPO_LABEL",
    "REPO_URL",
    "WALLETS",
    "app_icon",
    "app_icon_path",
    "wallet_icon_path",
    "wallets_html",
    "wallets_markdown",
]

#: Where the source lives (About dialog + Help menu).
REPO_URL = "https://github.com/khodekia/saccade"
REPO_LABEL = "github.com/khodekia/saccade"

#: Bundled SVG assets (CC0 cryptocurrency icons + the app icon).
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# (icon key, display label, network, address)
WALLETS: list[tuple[str, str, str, str]] = [
    ("btc", "Bitcoin (BTC)", "BTC network",
     "bc1q0m62svyqcl9n898yvccza4dx049c3uuqqg28zj"),
    ("eth", "Ethereum (ETH)", "ETH network",
     "0x1808eA06242729efA2E5a7B9c212530169011392"),
    ("usdc", "USDC", "Ethereum network",
     "0x1808eA06242729efA2E5a7B9c212530169011392"),
    ("doge", "Dogecoin (DOGE)", "Doge network",
     "DGfQtSnAgqBXzeuyQSmKLeMgaiVT5Rt1pT"),
    ("ton", "Toncoin", "TON network",
     "UQDTgx7WQZHOc8IAkhuIn2srrJj0XjOLT8Ej1nssfAhyKtq9"),
]


def wallet_icon_path(key: str) -> str:
    """Absolute path of the bundled logo for *key*, or '' when missing."""
    path = os.path.join(_ASSETS_DIR, "wallets", f"{key}.svg")
    return path if os.path.exists(path) else ""


def app_icon_path() -> str:
    """Absolute path of the bundled app icon, or '' when missing."""
    path = os.path.join(_ASSETS_DIR, "app.svg")
    return path if os.path.exists(path) else ""


def app_icon():
    """The application icon: bundled SVG first, theme icon as fallback."""
    from PyQt6.QtGui import QIcon

    path = app_icon_path()
    if path:
        return QIcon(path)
    return QIcon.fromTheme("saccade")


def wallets_html() -> str:
    """Rich-text block for the About dialog (logos + selectable addresses)."""
    rows = []
    for key, label, net, addr in WALLETS:
        icon = wallet_icon_path(key)
        logo = (
            f"<img src='file://{icon}' width='18' height='18'>&nbsp;&nbsp;"
            if icon else ""
        )
        rows.append(
            f"<p style='margin:5px 0'>{logo}<b>{html.escape(label)}</b>"
            f" <i style='color:#8a8f98'>({html.escape(net)})</i><br>"
            f"<code>{html.escape(addr)}</code></p>"
        )
    return ("<p><b>Support the project</b></p>"
            "<p style='margin-top:2px'>If Saccade is useful to you, you can "
            "send a donation to any of these addresses (click to select, "
            "Ctrl+C to copy):</p>" + "".join(rows))


def wallets_markdown() -> str:
    """Markdown block for the README."""
    lines = ["", "## Support the project", "",
             "If Saccade is useful to you, donations are appreciated:", ""]
    for _key, label, net, addr in WALLETS:
        lines += [f"**{label}** — *{net}*", "", "```", addr, "```", ""]
    return "\n".join(lines)

