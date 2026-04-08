from __future__ import annotations

from datetime import datetime, time


DAY_SESSION_START = time(8, 45)
DAY_SESSION_END = time(13, 45)
NIGHT_SESSION_START = time(15, 0)
NIGHT_SESSION_END = time(5, 0)


def classify_session(ts: datetime) -> str:
    current = ts.time()
    if DAY_SESSION_START <= current <= DAY_SESSION_END:
        return "day"
    if current >= NIGHT_SESSION_START or current < NIGHT_SESSION_END:
        return "night"
    return "unknown"
