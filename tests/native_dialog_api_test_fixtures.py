from __future__ import annotations

import pytest

from olga_companion.agent import session_token


@pytest.fixture
def token() -> str:
    return session_token.boot_token()
