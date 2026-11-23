"""0.1.27: every user-facing document tells the same update story.

The update key changed twice (0.1.24 hand-over, 0.1.25 rotation), so a version older than 0.1.25
cannot verify current releases and must be installed by hand once. Users read this in the README,
not only on the release page.
"""

from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).parent.parent
CURRENT_KEY_ID = "8CBC15C2BC59B946"


def _read(name: str) -> str:
    return (PROJECT / name).read_text(encoding="utf-8")


def test_both_readmes_explain_the_one_time_manual_install_and_link_the_key_doc() -> None:
    for name in ("README.md", "README.ko.md"):
        text = _read(name)
        assert "0.1.25" in text, f"{name} names the version that needs a manual install"
        assert "docs/UPDATER-KEY.md" in text, f"{name} links the updater key document"


def test_updater_key_doc_does_not_send_users_to_an_old_version() -> None:
    text = _read("docs/UPDATER-KEY.md")
    assert "Install 0.1.24 (or any later" not in text, "installing 0.1.24 no longer restores updates"
    assert "Signs 0.1.24 only" not in text, "the first key is the one 0.1.1-0.1.23 trust; it also signed 0.1.24"
    assert "latest release" in text
    assert CURRENT_KEY_ID in text
