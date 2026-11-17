"""Split a leading <think>...</think> block from a streamed answer.

Reasoning models behind some OpenAI-compatible servers (HD AIC among them) send their
reasoning inline before the answer. Only a block at the very start counts; a tag later
in the text is ordinary answer text.
"""

from __future__ import annotations

_OPEN = "<think>"
_CLOSE = "</think>"


class ThinkFilter:
    def __init__(self) -> None:
        self._state = "start"  # start -> inside -> answer
        self._buffer = ""

    def feed(self, text: str) -> tuple[str, str]:
        """Return (answer text, thinking text) that can be shown now."""
        if self._state == "answer":
            return text, ""
        self._buffer += text
        if self._state == "start":
            head = self._buffer.lstrip()
            if head.startswith(_OPEN):
                self._state = "inside"
                self._buffer = head[len(_OPEN):]
            elif _OPEN.startswith(head):
                return "", ""  # could still become the opening tag
            else:
                self._state = "answer"
                out, self._buffer = self._buffer, ""
                return out, ""
        end = self._buffer.find(_CLOSE)
        if end >= 0:
            thought, rest = self._buffer[:end], self._buffer[end + len(_CLOSE):]
            self._state = "answer"
            self._buffer = ""
            return rest.lstrip(), thought
        # Hold back a tail that may be the start of the closing tag.
        keep = next((n for n in range(len(_CLOSE) - 1, 0, -1) if self._buffer.endswith(_CLOSE[:n])), 0)
        thought = self._buffer[: len(self._buffer) - keep]
        self._buffer = self._buffer[len(self._buffer) - keep:]
        return "", thought

    def flush(self) -> tuple[str, str]:
        """End of stream: release whatever is still held back."""
        out, self._buffer = self._buffer, ""
        if self._state == "inside":
            return "", out
        return out, ""
