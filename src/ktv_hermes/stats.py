"""Fun statistics over past reservations."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .models import Activity

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def compute_stats(history: list[Activity]) -> dict:
    if not history:
        return {"total": 0}
    items = sorted(history, key=lambda a: a.start)
    first, last = items[0].start, items[-1].start
    weeks_span = max(1, ((last.date() - first.date()).days // 7) + 1)
    hours = sum((a.end - a.start for a in items), timedelta()).total_seconds() / 3600
    mondays = sorted({a.start.date() - timedelta(days=a.start.weekday()) for a in items})
    longest = current = 1
    for prev, cur in zip(mondays, mondays[1:]):
        current = current + 1 if (cur - prev).days == 7 else 1
        longest = max(longest, current)

    def top(counter: Counter, n: int = 5) -> list[dict]:
        return [{"value": k, "count": v} for k, v in counter.most_common(n)]

    return {
        "total": len(items),
        "total_hours": round(hours, 1),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "average_per_week": round(len(items) / weeks_span, 2),
        "active_weeks": len(mondays),
        "longest_weekly_streak": longest,
        "by_activity": top(Counter(a.name.upper() for a in items), 20),  # site mixes "ASC posilovna"/"ASC POSILOVNA"
        "by_kind": top(Counter(a.kind.value for a in items)),
        "by_weekday": top(Counter(WEEKDAYS[a.start.weekday()] for a in items), 7),
        "by_start_time": top(Counter(a.start.strftime("%H:%M") for a in items)),
        "by_month": top(Counter(a.start.strftime("%Y-%m") for a in items), 24),
        "by_year": top(Counter(str(a.start.year) for a in items), 10),
    }
