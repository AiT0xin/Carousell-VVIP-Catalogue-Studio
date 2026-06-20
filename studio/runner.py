"""Run a Playwright-backed stage in-process without tripping Streamlit.

Sync Playwright can't `start()` on a thread that already has a running asyncio
event loop — which Streamlit's script thread does. The fix is to run the stage
on a *fresh* background thread (no loop of its own) and stream progress back to
the Streamlit thread through a queue. The background thread only touches plain
Python objects (the session + the queue), never `st.*`, so it needs no
ScriptRunContext.

Usage:
    def stage(emit):
        run_qrcheck(sess, progress_cb=lambda i, n, r: emit({"i": i, "n": n, ...}))
        return summary
    for kind, payload in threaded_stage(stage):
        if kind == "progress": ...
        elif kind == "error":  ...   # payload is a traceback string
        elif kind == "result": ...   # payload is stage()'s return value
"""
from __future__ import annotations

import queue
import threading
import traceback
from typing import Callable, Iterator, Tuple, Any


def threaded_stage(stage: Callable[[Callable[[dict], None]], Any]) -> Iterator[Tuple[str, Any]]:
    """Run `stage(emit)` on a background thread; yield ('progress'|'error'|'result', payload)."""
    q: "queue.Queue[tuple]" = queue.Queue()
    box: dict = {}

    def emit(ev: dict) -> None:
        q.put(("progress", ev))

    def worker() -> None:
        try:
            box["result"] = stage(emit)
        except Exception:
            box["error"] = traceback.format_exc()
        finally:
            q.put(("done", None))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    while True:
        kind, payload = q.get()
        if kind == "progress":
            yield "progress", payload
        else:
            break

    if "error" in box:
        yield "error", box["error"]
    else:
        yield "result", box.get("result")
