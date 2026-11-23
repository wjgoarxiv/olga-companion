"""A stand-in for the `claude` CLI, driven by the JSON scenario named in FAKE_CLAUDE_SCENARIO.

Scenario keys (all optional):
  capture       file to write {"argv": [...], "env": {...}, "stdin": "..."} to
  version       text printed for --version          (default "2.1.220 (Claude Code)")
  help          text printed for --help             (default: every flag the app needs)
  replay        a .jsonl file whose lines are written to stdout
  lines         list of objects written as JSON lines
  echo_prompt   write {"type":"echo","text": <stdin>} as one JSON line
  big_line      write one JSON line of about this many bytes
  raw           latin-1 string written as raw bytes (for undecodable output)
  grandchild    file to write the pid of a sleeping child process to
  rogue         list of {name, arguments} posted straight to the bridge with the config's secret
  rogue_out     file the bridge answers are written to
  sleep         seconds to sleep before exiting (after writing)
  exit          exit code (default 0)
"""

import json
import os
import subprocess
import sys
import time

FLAGS = ("--print --tools --mcp-config --strict-mcp-config --setting-sources --disable-slash-commands "
         "--no-session-persistence --output-format --verbose --allowedTools --model --input-format "
         "--include-partial-messages --permission-mode")


def _rogue(calls: list) -> list:
    """Act as a hostile CLI: take the secret from our MCP config and call the bridge directly."""
    import urllib.request

    config_path = sys.argv[sys.argv.index("--mcp-config") + 1]
    server = json.loads(open(config_path, encoding="utf-8").read())["mcpServers"]["olga-companion"]
    secret, port = server["env"]["OLGA_BRIDGE_SECRET"], server["env"]["OLGA_SIDECAR_PORT"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    answers = []
    for call in calls:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/bridge/call", data=json.dumps(call).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Bridge-Secret": secret})
        try:
            with opener.open(request, timeout=10) as response:
                answers.append({"status": response.status, "body": json.loads(response.read())})
        except Exception as exc:  # noqa: BLE001 — record whatever the app answered
            answers.append({"status": getattr(exc, "code", 0), "body": str(exc)})
    return answers


def main() -> int:
    path = os.environ.get("FAKE_CLAUDE_SCENARIO", "")
    scenario = json.loads(open(path, encoding="utf-8").read()) if path else {}
    out = sys.stdout.buffer
    if sys.argv[-1:] == ["--version"]:
        out.write((scenario.get("version", "2.1.220 (Claude Code)") + "\n").encode())
        return 0
    if sys.argv[-1:] == ["--help"]:
        out.write(scenario.get("help", FLAGS).encode())
        return 0
    prompt = sys.stdin.buffer.read().decode("utf-8")
    if scenario.get("capture"):
        with open(scenario["capture"], "w", encoding="utf-8") as fh:
            json.dump({"argv": sys.argv[1:], "env": dict(os.environ), "stdin": prompt}, fh, ensure_ascii=False)
    if scenario.get("rogue"):
        answers = _rogue(scenario["rogue"])
        with open(scenario["rogue_out"], "w", encoding="utf-8") as fh:
            json.dump(answers, fh, ensure_ascii=False)
    if scenario.get("grandchild"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        with open(scenario["grandchild"], "w", encoding="utf-8") as fh:
            fh.write(str(child.pid))
    if scenario.get("replay"):
        with open(scenario["replay"], "rb") as fh:
            out.write(fh.read())
    for line in scenario.get("lines", []):
        out.write(json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n")
    if scenario.get("echo_prompt"):
        out.write(json.dumps({"type": "echo", "text": prompt}, ensure_ascii=False).encode("utf-8") + b"\n")
    if scenario.get("big_line"):
        out.write(json.dumps({"type": "big", "text": "x" * int(scenario["big_line"])}).encode() + b"\n")
    if scenario.get("raw"):
        out.write(scenario["raw"].encode("latin-1") + b"\n")
    out.flush()
    if scenario.get("sleep"):
        time.sleep(float(scenario["sleep"]))
    return int(scenario.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
