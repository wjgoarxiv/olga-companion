# Claude Code CLI fixtures

`claude -p --output-format stream-json --verbose` output, one JSON event per line, used by
`tests/test_claude_cli_stream.py`. Session ids, uuids, request ids, working folders, memory paths
and plugin names are replaced with placeholders. No sign-in data is in any file.

| File | Source |
| --- | --- |
| `happy.jsonl` | Captured, Claude Code 2.1.330 (WSL), plain Korean reply |
| `tool_read.jsonl` | Captured, 2.1.330, one allowed MCP read tool (`probe_echo`) |
| `tool_denied.jsonl` | Captured, 2.1.330, a tool not in `--allowedTools`; the CLI refused it (`system/permission_denied`) |
| `not_logged_in.jsonl` | Captured, 2.1.220 (Windows), empty profile folder |
| `login_expired.jsonl` | Captured, 2.1.220 (Windows), expired OAuth session |
| `synthetic_*.jsonl` | Synthetic, hand-made from the captured events: 401, 403, 429, rejected rate limit, a leaked built-in tool, a foreign MCP server, a forged "Not logged in" in a normal reply, garbage lines |

`fake_claude.py` stands in for the CLI in process tests; see its docstring for scenario keys.
Regenerate the real files with `.litclaude/tmp/cc_capture_wsl.py` and `.litclaude/tmp/cc_probe.py`,
then `.litclaude/tmp/cc_make_fixtures.py` (developer machine only).
