from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ktv_hermes.models import PRAGUE, Activity, Gender, Kind, sauna_allowed
from ktv_hermes.parser import parse_enroll_form, parse_week
from ktv_hermes.service import calendar_event
from ktv_hermes.stats import compute_stats

FIXTURES = Path(__file__).parent / "fixtures"


def _week():
    return {a.activity_id: a for a in parse_week((FIXTURES / "week.html").read_text(), 2026, 44)}


def test_parse_week_dates_kinds_and_enrollment():
    acts = _week()
    assert set(acts) == {101, 102, 201, 202}  # the full-hall reservation block is not an activity
    gym = acts[102]
    assert gym.kind is Kind.GYM and gym.enrolled and gym.is_full
    assert gym.start == datetime(2026, 10, 26, 16, 0, tzinfo=PRAGUE)
    assert gym.end - gym.start == timedelta(hours=2)
    assert not acts[101].enrolled and (acts[101].occupied, acts[101].capacity) == (5, 40)
    sauna = acts[201]
    assert sauna.kind is Kind.SAUNA and sauna.place == "SAUNA mužská šatna"
    assert sauna.start.date().isoformat() == "2026-10-27"


def test_parse_week_uses_iso_week_across_year_boundary():
    # ISO week 1 of 2026 starts on Monday 2025-12-29 (the site uses ISO weeks: 2026-W43 = Mon 19.10.).
    acts = parse_week((FIXTURES / "week.html").read_text(), 2026, 1)
    assert min(a.start for a in acts).date().isoformat() == "2025-12-29"


def _sauna(name: str, place: str) -> Activity:
    t = datetime(2026, 10, 27, 15, 0, tzinfo=PRAGUE)
    return Activity(1, name, place, t, t + timedelta(hours=2), 0, 13, False)


@pytest.mark.parametrize(
    ("name", "place", "gender", "allowed"),
    [
        ("Sauna MUŽI", "SAUNA mužská šatna", Gender.MALE, True),
        ("Sauna MUŽI", "SAUNA ženská šatna", Gender.MALE, True),  # men-only block uses both rooms
        ("Sauna MUŽI", "SAUNA mužská šatna", Gender.FEMALE, False),
        ("Sauna ŽENY", "SAUNA ženská šatna", Gender.FEMALE, True),
        ("Sauna ŽENY", "SAUNA mužská šatna", Gender.MALE, False),
        ("Sauna SPOLEČNÁ", "SAUNA mužská šatna", Gender.MALE, True),
        ("Sauna SPOLEČNÁ", "SAUNA ženská šatna", Gender.MALE, False),  # mixed: own changing room only
        ("Sauna SPOLEČNÁ", "SAUNA ženská šatna", Gender.FEMALE, True),
        ("Sauna DĚTI", "SAUNA mužská šatna", Gender.MALE, False),  # unknown session type is refused
        ("Sauna SPOLEČNÁ", "SAUNA", Gender.MALE, False),  # unknown room is refused
        ("Sauna SPOLEČNÁ (MUŽI)", "SAUNA ženská šatna", Gender.MALE, True),  # seen in real history: men-only
        ("Sauna SPOLEČNÁ (MUŽI)", "SAUNA ženská šatna", Gender.FEMALE, False),
    ],
)
def test_sauna_gender_rules(name, place, gender, allowed):
    assert sauna_allowed(_sauna(name, place), gender)[0] is allowed


ENROLL_FORM = """
<form class="modal-content" action="/asc?ascCalendarComponent-year=2026&amp;ascCalendarComponent-week=44&amp;ascCalendarComponent-enrollActivityId=101" method="post">
 <div class="modal-header"><div class="modal-title"><h5><i class="fa fa-users"></i> Přihlášení na ASC POSILOVNA </h5></div></div>
 <div class="modal-body">
  <div><b>Termín: </b><span>26.10.2026 v 09:00-12:00</span></div>
  <div><b>Místo:</b> KTV - POSILOVNA</div>
  <div><b>Cena pro veřejnost:</b> 110 Kč</div>
 </div>
 <div class="modal-footer"><button type="submit" name="{button}" value="x">x</button></div>
 <input type="hidden" name="_do" value="ascCalendarComponent-activityEnrollForm-activityEnrollForm-submit">
</form>
"""


def test_enroll_form_states():
    free = parse_enroll_form(ENROLL_FORM.replace("{button}", "_submit"))
    assert free.can_enroll and not free.enrolled
    assert free.action.endswith("enrollActivityId=101")
    assert free.fields == {"_do": "ascCalendarComponent-activityEnrollForm-activityEnrollForm-submit"}
    assert free.start == datetime(2026, 10, 26, 9, 0, tzinfo=PRAGUE)
    assert free.place == "KTV - POSILOVNA" and free.title == "ASC POSILOVNA"
    booked = parse_enroll_form(ENROLL_FORM.replace("{button}", "optOut"))
    assert booked.enrolled and not booked.can_enroll


def test_calendar_event_uses_utc_and_links_activity():
    act = _week()[102]
    ev = calendar_event(act)
    assert "DTSTART:20261026T150000Z" in ev["ics"]  # 16:00 CET = 15:00 UTC
    assert ev["uid"] == "ktv-102@rezervace.ktv.tul.cz"
    assert "ktv-activity-id: 102" in ev["description"]


def test_stats_counts_and_streak():
    base = datetime(2026, 1, 5, 18, 0, tzinfo=PRAGUE)  # a Monday
    weeks = [0, 1, 2, 4]
    acts = [Activity(i, "ASC POSILOVNA", "KTV - POSILOVNA", base + timedelta(weeks=w),
                     base + timedelta(weeks=w, hours=2), 1, 30, True) for i, w in enumerate(weeks)]
    s = compute_stats(acts)
    assert s["total"] == 4 and s["total_hours"] == 8.0
    assert s["longest_weekly_streak"] == 3 and s["active_weeks"] == 4
    assert s["by_weekday"][0] == {"value": "Monday", "count": 4}
    assert compute_stats([]) == {"total": 0}
