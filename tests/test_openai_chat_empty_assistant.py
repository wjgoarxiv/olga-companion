"""A blank assistant reply never reaches a Chat Completions request.

After tool results the runtime may store a blank reply and ask the provider once more
to answer. An assistant message with no content and no tool calls is not a valid Chat
Completions message, so the builder leaves it out, as the Responses builder does.
"""
from __future__ import annotations

from olga_companion.llm.openai_chat_adapter import OpenAIChatConversationBuilder
from olga_companion.llm.protocol import ToolCall


def test_a_blank_reply_without_tool_calls_is_not_sent() -> None:
    conversation = OpenAIChatConversationBuilder()
    conversation.add_user_message("plot it")
    conversation.add_assistant_response("", [ToolCall(call_id="c1", name="results_plot", args={})])
    conversation.add_tool_result("c1", "results_plot", "{}")
    conversation.add_assistant_response("")
    conversation.add_assistant_response("  \n")
    conversation.add_user_message("(automatic) answer now")

    messages = conversation._messages
    assistants = [m for m in messages if m["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["tool_calls"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "user"]


def test_a_reply_with_text_is_kept() -> None:
    conversation = OpenAIChatConversationBuilder()
    conversation.add_assistant_response("Inlet PT is 8.2 bar.")

    assert conversation._messages == [{"role": "assistant", "content": "Inlet PT is 8.2 bar."}]
