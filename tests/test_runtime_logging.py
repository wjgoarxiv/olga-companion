import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
import httpx
import pytest
from fastapi import FastAPI, Request

from olga_companion import runtime_logging


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_logging, "project_root", lambda: tmp_path)
    path = runtime_logging.configure_file_logging()
    yield path
    logger = logging.getLogger(runtime_logging.LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_file_log_is_bounded_and_reconfiguration_does_not_duplicate(log_path):
    runtime_logging.configure_file_logging()
    logger = logging.getLogger(runtime_logging.LOGGER_NAME)
    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert handler.maxBytes == 1_048_576
    assert handler.backupCount == 3
    assert logger.propagate is False
    logger.info("runtime_started")
    assert log_path.read_text(encoding="utf-8").count("runtime_started") == 1


def test_diagnostics_record_route_status_and_error_type_without_private_input(log_path):
    app = FastAPI()
    runtime_logging.install_request_diagnostics(app)

    @app.post("/api/example/{case_id}")
    async def fail(case_id: str, request: Request):
        raise RuntimeError(f"secret-token {case_id} {await request.body()}")

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client:
            response = await client.post(
                "/api/example/private-case?token=private-query",
                headers={"Authorization": "Bearer private-header"},
                json={"text": "private-chat"},
            )
            assert response.status_code == 500
            assert (await client.get("/private-unmatched-path")).status_code == 404

    asyncio.run(exercise())
    text = log_path.read_text(encoding="utf-8")
    assert "/api/example/{case_id}" in text
    assert "status=500" in text and "RuntimeError" in text
    assert "status=404" in text and "route=unmatched" in text
    for private in ("secret-token", "private-case", "private-query", "private-header", "private-chat", "private-unmatched-path"):
        assert private not in text


def test_unwritable_logging_does_not_prevent_startup(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime_logging, "project_root", lambda: tmp_path / "blocked")
    (tmp_path / "blocked").write_text("not a directory", encoding="utf-8")
    assert runtime_logging.configure_file_logging() is None
    assert "diagnostic file logging is unavailable" in capsys.readouterr().err


def test_unrelated_provider_logs_are_not_written_to_diagnostics(log_path):
    logging.getLogger("olga_companion.llm.transport").warning("provider-secret")
    assert "provider-secret" not in log_path.read_text(encoding="utf-8")


def test_streamed_provider_failure_is_recorded_without_exception_body(log_path):
    from olga_companion.agent import runtime

    class FailedClient:
        def create_conversation(self, model):
            return self

        def add_user_message(self, message):
            pass

        async def stream_generate(self, **kwargs):
            raise RuntimeError("transport failed Bearer provider-credential-and-private-chat")

    async def exercise():
        return [event async for event in runtime.run_turn(FailedClient(), "private-input")]

    events = asyncio.run(exercise())
    assert events[0].type == "error"
    assert events[0].data["message"] == "응답을 만들지 못했습니다. 공급자 연결을 확인하고 다시 시도하세요."
    text = log_path.read_text(encoding="utf-8")
    assert "chat_failed stage=provider_generation kind=RuntimeError status=None detail=" in text
    assert "transport failed" in text
    assert "<redacted>" in text
    assert "Bearer provider-credential-and-private-chat" not in text
    assert "private-input" not in text


def test_409_conflict_code_is_logged_without_response_body(log_path):
    from fastapi.responses import JSONResponse

    app = FastAPI()
    runtime_logging.install_request_diagnostics(app)

    @app.post("/api/approvals/execute")
    async def conflict():
        return JSONResponse(
            status_code=409,
            content={
                "code": "approval_context_changed",
                "message": "secret-body-must-not-appear",
            },
        )

    @app.post("/api/approvals/unknown")
    async def conflict_without_code():
        return JSONResponse(status_code=409, content={"state": "failed"})

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client:
            coded = await client.post("/api/approvals/execute")
            assert coded.status_code == 409
            assert coded.json() == {
                "code": "approval_context_changed",
                "message": "secret-body-must-not-appear",
            }
            assert (await client.post("/api/approvals/unknown")).status_code == 409

    asyncio.run(exercise())
    text = log_path.read_text(encoding="utf-8")
    assert "status=409" in text
    assert "code=approval_context_changed" in text
    assert "secret-body-must-not-appear" not in text
    assert text.count("code=") == 1


def test_real_sidecar_entrypoint_writes_private_safe_diagnostics(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {**os.environ, "OLGA_APP_DATA_DIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "olga_companion.sidecar", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            while True:
                try:
                    response = client.get("/api/workspace/context?token=private-probe")
                    if response.status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None, "sidecar exited before readiness"
                assert time.monotonic() < deadline, "sidecar startup timed out"
                time.sleep(0.1)
        text = (tmp_path / "var" / "logs" / "sidecar.log").read_text(encoding="utf-8")
        assert "runtime_start version=" in text
        assert "status=401" in text
        assert "private-probe" not in text
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
