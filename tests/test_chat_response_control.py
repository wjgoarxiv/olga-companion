from __future__ import annotations

import asyncio

from olga_companion.agent import chat_response_control


def test_stop_response_targets_only_the_registered_chat_task() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()

        async def response() -> None:
            async with chat_response_control.active_response("session-123456"):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(response())
        await entered.wait()
        receipt = chat_response_control.stop_response("session-123456")
        assert receipt == {"stopped": True, "session_id": "session-123456"}
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("registered response task was not cancelled")

    asyncio.run(scenario())


def test_stop_response_is_idempotent_for_inactive_session() -> None:
    assert chat_response_control.stop_response("inactive-123456") == {
        "stopped": False,
        "session_id": "inactive-123456",
    }
