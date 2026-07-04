"""Convert session logs to the simple bench transcript schema (S4).

Bench schema — one JSON object per line:
    {"role": "user"|"assistant", "content": "<text>", "ts": <optional number>}

``from_claude_code`` maps a Claude Code ``.jsonl`` export onto it. The export
format is read defensively (only role + text are needed); it is marked
experimental because it is verified against the sessions on this machine, not
a published spec.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def from_claude_code(path: str | Path) -> Iterator[dict[str, object]]:
    """Yield bench-schema rows from a Claude Code session .jsonl (experimental)."""
    for raw in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        text = _text(msg.get("content", "")).strip()
        if text:
            yield {"role": str(msg.get("role", "")), "content": text}


def write_bench_jsonl(rows: Iterator[dict[str, object]], out: str | Path) -> int:
    n = 0
    with Path(out).open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
            n += 1
    return n
