"""
Lantern - Auto-updater module
Checks GitHub releases for new versions on startup.
"""

import json
import subprocess
import sys
from typing import Optional

GITHUB_REPO = "shx-dow/lantern"
UPDATE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_version() -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "lantern-p2p"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "0.0.0"


def get_latest_version() -> Optional[str]:
    try:
        import urllib.request

        req = urllib.request.Request(
            UPDATE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Lantern-Updater",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception:
        return None


def check_for_updates() -> None:
    current = get_current_version()
    latest = get_latest_version()

    if latest is None:
        return

    if current != latest:
        print(f"\n!! : Update available: v{latest} (you have v{current})")
        print("Run: pip install --upgrade lantern-p2p\n")
