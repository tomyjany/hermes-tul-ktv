"""MCP server (stdio) exposing the KTV reservation system as tools."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from functools import lru_cache, wraps

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import KTVClient, KTVError
from .models import PRAGUE, Gender, Kind
from .service import KTVService

mcp = MCPServer(
    "ktv-hermes",
    instructions=(
        "Tools for the TUL KTV sports-centre reservation system (rezervace.ktv.tul.cz). "
        "Use find_gym_slots / find_sauna_slots to get activity_id values, then book_gym / book_sauna. "
        "Every booking/cancellation returns a `calendar` object (summary, start, end, location, uid, ics): "
        "create the matching calendar event after booking and delete it after cancelling "
        "(find it by the `ktv-activity-id: N` line in its description). Dates are ISO (YYYY-MM-DD), times Europe/Prague."
    ),
)


@lru_cache(maxsize=1)
def _service() -> KTVService:
    load_dotenv()
    gender = os.environ.get("KTV_GENDER", "").strip().lower() or None
    return KTVService(
        KTVClient(os.environ.get("KTV_USERNAME", ""), os.environ.get("KTV_PASSWORD", "")),
        default_gender=Gender(gender) if gender else None,
    )


def _range(date_from: str | None, date_to: str | None, default_days: int = 7) -> tuple[date, date]:
    start = date.fromisoformat(date_from) if date_from else datetime.now(PRAGUE).date()
    end = date.fromisoformat(date_to) if date_to else start + timedelta(days=default_days)
    if end < start:
        raise ValueError("date_to must not be before date_from")
    return start, end


def _gender(value: str | None) -> Gender | None:
    if not value:
        return None
    g = Gender(value.strip().lower())
    if g is Gender.MIXED:
        raise ValueError("gender must be 'male' or 'female'")
    return g


def _tool(fn):
    """Register ``fn`` as an MCP tool; expected failures reach the agent as readable tool errors."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (KTVError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp.tool()(wrapper)


@_tool
def find_gym_slots(date_from: str | None = None, date_to: str | None = None, only_available: bool = True) -> list[dict]:
    """List future gym (ASC POSILOVNA) blocks between two dates (default: next 7 days), with occupancy."""
    start, end = _range(date_from, date_to)
    return _service().find_slots(Kind.GYM, start, end, only_available=only_available)


@_tool
def find_sauna_slots(date_from: str | None = None, date_to: str | None = None, only_available: bool = True,
                     gender: str | None = None) -> list[dict]:
    """List future sauna blocks (default: next 7 days). With only_available, shows only blocks the given gender
    (default KTV_GENDER) may book: the title must name that gender (MUŽI/ŽENY) and the row must be its own changing room."""
    start, end = _range(date_from, date_to)
    return _service().find_slots(Kind.SAUNA, start, end, only_available=only_available, gender=_gender(gender))


@_tool
def upcoming_reservations(weeks_ahead: int = 4) -> list[dict]:
    """My booked activities that haven't ended yet, each with a ready-made `calendar` event payload."""
    return _service().upcoming(weeks_ahead)


@_tool
def reservation_history(since: str | None = None) -> list[dict]:
    """My past reservations since a date (default: 365 days ago). Older weeks are cached locally."""
    start = date.fromisoformat(since) if since else datetime.now(PRAGUE).date() - timedelta(days=365)
    return [a.to_dict() for a in _service().history(start)]


@_tool
def reservation_stats(since: str | None = None) -> dict:
    """Fun statistics over past reservations (totals, hours, per weekday/time/month, streaks)."""
    start = date.fromisoformat(since) if since else datetime.now(PRAGUE).date() - timedelta(days=365)
    return _service().stats(start)


@_tool
def book_gym(activity_id: int) -> dict:
    """Book a gym block by activity_id (from find_gym_slots). Payment happens on site."""
    return _service().book(activity_id, Kind.GYM)


@_tool
def book_sauna(activity_id: int, gender: str | None = None) -> dict:
    """Book a sauna block by activity_id (from find_sauna_slots). Refuses blocks not allowed for the gender."""
    return _service().book(activity_id, Kind.SAUNA, _gender(gender))


@_tool
def cancel_reservation(activity_id: int) -> dict:
    """Cancel one of my reservations (gym or sauna) by activity_id."""
    return _service().cancel(activity_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
