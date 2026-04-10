from __future__ import annotations

from datetime import date, datetime, time, timedelta


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


def trading_day_for(ts: datetime) -> date:
    if classify_session(ts) != "night":
        return ts.date()
    if ts.time() < NIGHT_SESSION_END:
        return (ts - timedelta(days=1)).date()
    return ts.date()


def iter_expected_bar_timestamps(
    start: datetime,
    end: datetime,
    step: timedelta,
    session_scope: str,
) -> list[datetime]:
    timestamps: list[datetime] = []
    trading_day = trading_day_for(start)
    end_trading_day = trading_day_for(end)

    while trading_day <= end_trading_day:
        for session_start, session_end in session_windows_for(trading_day, session_scope):
            window_start = max(start, session_start)
            window_end = min(end, session_end)
            if window_start > window_end:
                continue
            current = window_start
            while current <= window_end:
                timestamps.append(current)
                current += step
        trading_day += timedelta(days=1)
    return timestamps


def _is_in_scope(ts: datetime, session_scope: str) -> bool:
    session = classify_session(ts)
    if session_scope == "day":
        return session == "day"
    if session_scope == "night":
        return session == "night"
    if session_scope == "day_and_night":
        return session in {"day", "night"}
    raise ValueError(f"Unsupported session scope: {session_scope}")


def session_windows_for(trading_day: date, session_scope: str) -> list[tuple[datetime, datetime]]:
    day_session = (
        datetime.combine(trading_day, DAY_SESSION_START),
        datetime.combine(trading_day, DAY_SESSION_END),
    )
    night_session = (
        datetime.combine(trading_day, NIGHT_SESSION_START),
        datetime.combine(trading_day + timedelta(days=1), NIGHT_SESSION_END) - timedelta(minutes=1),
    )

    if session_scope == "day":
        return [day_session]
    if session_scope == "night":
        return [night_session]
    if session_scope == "day_and_night":
        return [day_session, night_session]
    raise ValueError(f"Unsupported session scope: {session_scope}")
