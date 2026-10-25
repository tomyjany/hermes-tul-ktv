"""Parsers for rezervace.ktv.tul.cz HTML (weekly ASC calendar and the enroll modal)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from bs4 import BeautifulSoup

from .models import PRAGUE, Activity

_TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_OCCUPANCY = re.compile(r"(\d+)\s*/\s*(\d+)")
_ACTIVITY_ID = re.compile(r"activityId=(\d+)")
_TERM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*v\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def is_logged_in(html: str) -> bool:
    return "/homepage/logout" in html


def flash_messages(html: str) -> list[str]:
    """Nette flash/alert texts shown after a form submit."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for el in soup.select('[class*="alert"], [class*="flash"]'):
        text = " ".join(el.get_text(" ", strip=True).split())
        if text and text not in out:
            out.append(text)
    return out


def _at(day: date, hh: str, mm: str) -> datetime:
    return datetime.combine(day, time(int(hh), int(mm)), tzinfo=PRAGUE)


def parse_week(html: str, year: int, week: int) -> list[Activity]:
    """All activity blocks of one ISO week (all areas shown by the page)."""
    monday = date.fromisocalendar(year, week, 1)
    soup = BeautifulSoup(html, "html.parser")
    activities: list[Activity] = []
    for day_index, day_el in enumerate(soup.select("div.c-asc-table__day")):
        day = monday + timedelta(days=day_index)
        for row in day_el.select("div.c-asc-table__row"):
            label = row.select_one(".c-asc-table__sidebar-col span")
            place = (label.get("title") or label.get_text(strip=True)) if label else ""
            for item in row.select("div.c-asc-table__item--activity"):
                act = _parse_item(item, place.strip(), day)
                if act:
                    activities.append(act)
    return activities


def _parse_item(item, place: str, day: date) -> Activity | None:
    link = item.select_one("a[href*='activityId=']")
    name_el = item.select_one(".c-asc-table__info-detail")
    if not link or not name_el:
        return None
    match = _ACTIVITY_ID.search(link["href"])
    lis = [" ".join(li.get_text(" ", strip=True).split()) for li in item.select("ul.c-asc-table__list li")]
    times = next((m for m in (_TIME_RANGE.search(x) for x in lis) if m), None)
    if not match or not times:
        return None
    occ = next((_OCCUPANCY.search(x) for x in lis if x.startswith("Obsazenost")), None)
    instructor = next((x.split(":", 1)[1].strip() for x in lis if x.startswith("Vyučující")), "")
    start = _at(day, times.group(1), times.group(2))
    end = _at(day, times.group(3), times.group(4))
    if end <= start:
        end += timedelta(days=1)
    return Activity(
        activity_id=int(match.group(1)),
        name=" ".join(name_el.get_text(" ", strip=True).split()),
        place=place,
        start=start,
        end=end,
        occupied=int(occ.group(1)) if occ else 0,
        capacity=int(occ.group(2)) if occ else 0,
        enrolled="c-asc-table__item--logged-in" in item.get("class", []),
        instructor=instructor,
    )


@dataclass(frozen=True)
class EnrollForm:
    """The enroll/cancel modal returned by the ``ascCalendarComponent-enroll`` signal."""

    action: str
    fields: dict[str, str]
    title: str
    place: str
    start: datetime | None
    end: datetime | None
    enrolled: bool
    can_enroll: bool
    price_text: str


def parse_enroll_form(snippet_html: str) -> EnrollForm:
    soup = BeautifulSoup(snippet_html, "html.parser")
    form = soup.find("form")
    if form is None:
        raise ValueError("enroll snippet contains no form")
    fields = {
        inp["name"]: inp.get("value", "")
        for inp in form.select("input[type=hidden][name]")
    }
    buttons = {btn.get("name"): btn.get("value", "") for btn in form.select("button[type=submit][name]")}
    info = {}
    for div in form.select(".modal-body div"):
        bold = div.find("b")
        if bold:
            key = bold.get_text(strip=True).rstrip(":")
            info[key] = " ".join(div.get_text(" ", strip=True).split()[len(key.split()):]).lstrip(": ").strip()
    start = end = None
    term = _TERM.search(info.get("Termín", ""))
    if term:
        d = date(int(term.group(3)), int(term.group(2)), int(term.group(1)))
        start = _at(d, term.group(4), term.group(5))
        end = _at(d, term.group(6), term.group(7))
    title_el = form.select_one(".modal-title")
    title = " ".join(title_el.get_text(" ", strip=True).split()) if title_el else ""
    prices = [f"{k}: {v}" for k, v in info.items() if k.lower().startswith("cena")]
    return EnrollForm(
        action=form.get("action", ""),
        fields=fields,
        title=re.sub(r"^Přihlášení na\s*", "", title),
        place=info.get("Místo", ""),
        start=start,
        end=end,
        enrolled="optOut" in buttons,
        can_enroll="_submit" in buttons,
        price_text="; ".join(prices),
    )
