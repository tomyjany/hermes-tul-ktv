"""Use-case layer shared by the MCP server: history (cached), upcoming, booking rules, calendar payloads."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .client import KTVClient, KTVError
from .models import PRAGUE, Activity, Gender, Kind, sauna_allowed
from .stats import compute_stats

CACHE_DIR = Path.home() / ".cache" / "ktv-hermes"


def _activity_from_dict(d: dict) -> Activity:
    return Activity(
        activity_id=d["activity_id"],
        name=d["name"],
        place=d["place"],
        start=datetime.fromisoformat(d["start"]),
        end=datetime.fromisoformat(d["end"]),
        occupied=d["occupied"],
        capacity=d["capacity"],
        enrolled=d["enrolled"],
        instructor=d.get("instructor", ""),
    )


def calendar_event(act: Activity) -> dict:
    """Everything a host agent needs to create (and later find/delete) a calendar event."""
    uid = f"ktv-{act.activity_id}@rezervace.ktv.tul.cz"
    summary = f"KTV: {act.name}"
    location = f"{act.place}, KTV TUL, Liberec"
    description = f"Booked via ktv-hermes (rezervace.ktv.tul.cz). ktv-activity-id: {act.activity_id}"
    fmt = "%Y%m%dT%H%M%SZ"
    ics = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ktv-hermes//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{act.start.astimezone(timezone.utc).strftime(fmt)}",
        f"DTEND:{act.end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:{summary}",
        f"LOCATION:{location.replace(',', chr(92) + ',')}",
        f"DESCRIPTION:{description}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])
    return {
        "uid": uid,
        "summary": summary,
        "start": act.start.isoformat(),
        "end": act.end.isoformat(),
        "timezone": "Europe/Prague",
        "location": location,
        "description": description,
        "ics": ics,
    }


class KTVService:
    def __init__(self, client: KTVClient, *, default_gender: Gender | None = None, cache_dir: Path = CACHE_DIR):
        self.client = client
        self.default_gender = default_gender
        key = hashlib.sha256(client.username.encode()).hexdigest()[:12]
        self.cache_file = cache_dir / f"history-{key}.json"

    # ---- queries ----------------------------------------------------------
    def find_slots(self, kind: Kind, date_from: date, date_to: date, *, only_available: bool = True,
                   gender: Gender | None = None) -> list[dict]:
        now = datetime.now(PRAGUE)
        out = []
        for act in self.client.activities_between(date_from, date_to):
            if act.kind is not kind or act.start <= now:
                continue
            if only_available and act.is_full and not act.enrolled:
                continue
            row = act.to_dict()
            if kind is Kind.SAUNA:
                g = gender or self.default_gender
                if g is None:
                    row["allowed"], row["allowed_reason"] = None, "set KTV_GENDER or pass gender"
                else:
                    row["allowed"], row["allowed_reason"] = sauna_allowed(act, g)
                    if only_available and not row["allowed"]:
                        continue
            out.append(row)
        return out

    def upcoming(self, weeks_ahead: int = 4) -> list[dict]:
        now = datetime.now(PRAGUE)
        acts = self.client.activities_between(now.date(), now.date() + timedelta(weeks=weeks_ahead))
        return [a.to_dict() | {"calendar": calendar_event(a)} for a in acts if a.enrolled and a.end >= now]

    def history(self, since: date) -> list[Activity]:
        """Past reservations since ``since``. Fully past weeks are cached on disk."""
        cache = self._load_cache()
        today = datetime.now(PRAGUE).date()
        now = datetime.now(PRAGUE)
        result: list[Activity] = []
        monday = since - timedelta(days=since.weekday())
        changed = False
        while monday <= today:
            iso = monday.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
            if key in cache:
                acts = [_activity_from_dict(d) for d in cache[key]]
            else:
                acts = [a for a in self.client.week(iso.year, iso.week) if a.enrolled]
                if monday + timedelta(days=7) <= today:
                    cache[key] = [a.to_dict() for a in acts]
                    changed = True
            result.extend(a for a in acts if a.start.date() >= since and a.end < now)
            monday += timedelta(days=7)
        if changed:
            self._save_cache(cache)
        return sorted(result, key=lambda a: a.start)

    def stats(self, since: date) -> dict:
        history = self.history(since)
        return {"since": since.isoformat(), **compute_stats(history)}

    # ---- mutations --------------------------------------------------------
    def book(self, activity_id: int, kind: Kind, gender: Gender | None = None) -> dict:
        act = self.client.find_activity(activity_id)
        if act.kind is not kind:
            raise KTVError(f"activity {activity_id} is {act.name!r} ({act.kind.value}), not a {kind.value}")
        if act.start <= datetime.now(PRAGUE):
            raise KTVError(f"activity {activity_id} already started")
        if kind is Kind.SAUNA:
            g = gender or self.default_gender
            if g is None:
                raise KTVError("sauna booking needs a gender: set KTV_GENDER=male|female or pass gender")
            ok, reason = sauna_allowed(act, g)
            if not ok:
                raise KTVError(f"refusing to book sauna: {reason}")
        _, messages = self.client.enroll(activity_id)
        booked = self.client.find_activity(activity_id)
        return {"status": "booked", "activity": booked.to_dict(), "messages": messages,
                "calendar": calendar_event(booked)}

    def cancel(self, activity_id: int) -> dict:
        act = self.client.find_activity(activity_id)
        _, messages = self.client.cancel(activity_id)
        return {"status": "cancelled", "activity": act.to_dict() | {"enrolled": False}, "messages": messages,
                "calendar": calendar_event(act)}

    # ---- cache ------------------------------------------------------------
    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(cache, ensure_ascii=False))
        self.cache_file.chmod(0o600)
