"""What the page is doing right now, including download bytes still left."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_state = {
    "active": False,
    "phase": "idle",
    "label": "",
    "received": 0,
    "total": 0,
}


def begin(phase: str, label: str) -> None:
    with _lock:
        _state.update(active=True, phase=phase, label=label, received=0, total=0)


def note(received: int, total: int) -> None:
    with _lock:
        _state["active"] = True
        _state["phase"] = "download"
        _state["received"] = max(0, int(received))
        _state["total"] = max(0, int(total))


def note_at_least(received: int, total: int) -> None:
    """Raise received/total without letting a quieter source pull them back down."""
    with _lock:
        _state["active"] = True
        _state["phase"] = "download"
        _state["received"] = max(int(_state["received"]), max(0, int(received)))
        new_total = max(0, int(total))
        if new_total > 0:
            _state["total"] = max(int(_state["total"]), new_total)


def progress(received: int, total: int, label: str | None = None) -> None:
    """Update counters without changing phase (unlike note())."""
    with _lock:
        _state["active"] = True
        _state["received"] = max(0, int(received))
        _state["total"] = max(0, int(total))
        if label is not None:
            _state["label"] = str(label)


def clear() -> None:
    with _lock:
        _state.update(active=False, phase="idle", label="", received=0, total=0)


def snapshot() -> dict:
    with _lock:
        received = int(_state["received"])
        total = int(_state["total"])
        remaining = max(0, total - received) if total else 0
        return {
            "active": bool(_state["active"]),
            "phase": _state["phase"],
            "label": _state["label"],
            "received": received,
            "total": total,
            "remaining": remaining,
        }
