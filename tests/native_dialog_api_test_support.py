from __future__ import annotations

from fastapi.testclient import TestClient

from olga_companion.sidecar import app


client = TestClient(app)


def _headers(token: str) -> dict[str, str]:
    return {"X-Session-Token": token}
