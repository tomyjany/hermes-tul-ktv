"""Data model and activity classification (gym / sauna / gender rules)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")


class Kind(str, Enum):
    GYM = "gym"
    SAUNA = "sauna"
    OTHER = "other"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    MIXED = "mixed"


@dataclass(frozen=True)
class Activity:
    """One bookable block from the weekly ASC calendar."""

    activity_id: int
    name: str
    place: str
    start: datetime
    end: datetime
    occupied: int
    capacity: int
    enrolled: bool
    instructor: str = ""

    @property
    def kind(self) -> Kind:
        return classify_kind(self.name, self.place)

    @property
    def is_full(self) -> bool:
        return self.occupied >= self.capacity

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        data["kind"] = self.kind.value
        data["full"] = self.is_full
        if self.kind is Kind.SAUNA:
            session = sauna_session_gender(self.name)
            room = changing_room_gender(self.place)
            data["sauna_session"] = session.value if session else None
            data["changing_room"] = room.value if room else None
        return data


def classify_kind(name: str, place: str) -> Kind:
    text = f"{name} {place}".lower()
    if "sauna" in text:
        return Kind.SAUNA
    if "posilovna" in text:
        return Kind.GYM
    return Kind.OTHER


def sauna_session_gender(name: str) -> Gender | None:
    """Who the sauna block is open for, from its title (e.g. 'Sauna MUŽI')."""
    upper = name.upper()
    if "MUŽI" in upper or "MUZI" in upper:
        return Gender.MALE
    if "ŽENY" in upper or "ZENY" in upper:
        return Gender.FEMALE
    if "SPOLEČN" in upper or "SPOLECN" in upper:
        return Gender.MIXED
    return None


def changing_room_gender(place: str) -> Gender | None:
    """Which changing room a sauna row uses (e.g. 'SAUNA mužská šatna')."""
    lower = place.lower()
    if re.search(r"\bmu[žz]sk", lower):
        return Gender.MALE
    if re.search(r"\b[žz]ensk", lower):
        return Gender.FEMALE
    return None


def sauna_allowed(activity: Activity, gender: Gender) -> tuple[bool, str]:
    """Whether a person of ``gender`` may book this sauna block.

    The row must always be your own changing room. The block itself must be either for your
    gender (``Sauna MUŽI``, ``Sauna SPOLEČNÁ (MUŽI)``) or mixed (``Sauna SPOLEČNÁ``).
    Anything unrecognised is refused rather than guessed.
    """
    if gender not in (Gender.MALE, Gender.FEMALE):
        return False, "gender must be 'male' or 'female'"
    session = sauna_session_gender(activity.name)
    room = changing_room_gender(activity.place)
    if session is None:
        return False, f"unrecognised sauna session type in {activity.name!r}"
    if session not in (gender, Gender.MIXED):
        return False, f"{activity.name!r} is a {session.value}-only sauna block"
    if room is None:
        return False, f"unrecognised changing room in {activity.place!r}"
    if room is not gender:
        return False, f"{activity.place!r} is the {room.value} changing room"
    return True, f"{session.value} block in the {room.value} changing room"
