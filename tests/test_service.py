from datetime import date, datetime, timedelta

import pytest

from ktv_hermes.client import KTVError
from ktv_hermes.models import PRAGUE, Activity, Gender, Kind
from ktv_hermes.service import KTVService


class FakeClient:
    username = "someone@example.com"

    def __init__(self, acts):
        self.acts = {a.activity_id: a for a in acts}
        self.week_calls = []
        self.enrolled = []

    def week(self, year, week):
        self.week_calls.append((year, week))
        return [a for a in self.acts.values() if a.start.isocalendar()[:2] == (year, week)]

    def activities_between(self, start, end):
        return [a for a in self.acts.values() if start <= a.start.date() <= end]

    def find_activity(self, activity_id):
        return self.acts[activity_id]

    def enroll(self, activity_id):
        self.enrolled.append(activity_id)
        a = self.acts[activity_id]
        self.acts[activity_id] = Activity(**{**a.__dict__, "enrolled": True})
        return None, []


def _act(i, name, place, start, enrolled=False):
    return Activity(i, name, place, start, start + timedelta(hours=2), 1, 13, enrolled)


def test_history_caches_only_completed_weeks(tmp_path):
    now = datetime.now(PRAGUE).replace(minute=0, second=0, microsecond=0)
    old = _act(1, "ASC POSILOVNA", "KTV - POSILOVNA", now - timedelta(weeks=3), enrolled=True)
    other = _act(2, "ASC POSILOVNA", "KTV - POSILOVNA", now - timedelta(weeks=3, days=1))  # not mine
    client = FakeClient([old, other])
    svc = KTVService(client, cache_dir=tmp_path)
    since = date.today() - timedelta(weeks=4)

    first = svc.history(since)
    assert [a.activity_id for a in first] == [1]
    calls_first = len(client.week_calls)

    client.week_calls.clear()
    second = svc.history(since)
    assert [a.activity_id for a in second] == [1]
    # Completed weeks come from the cache; only the current (incomplete) week is fetched again.
    assert 1 <= len(client.week_calls) < calls_first


def test_book_refuses_wrong_kind_and_wrong_gender_without_enrolling(tmp_path):
    future = datetime.now(PRAGUE) + timedelta(days=3)
    gym = _act(10, "ASC POSILOVNA", "KTV - POSILOVNA", future)
    women = _act(11, "Sauna ŽENY", "SAUNA ženská šatna", future)
    client = FakeClient([gym, women])
    svc = KTVService(client, default_gender=Gender.MALE, cache_dir=tmp_path)

    with pytest.raises(KTVError, match="not a sauna"):
        svc.book(10, Kind.SAUNA)
    with pytest.raises(KTVError, match="female-only"):
        svc.book(11, Kind.SAUNA)
    assert client.enrolled == []

    result = svc.book(10, Kind.GYM)
    assert client.enrolled == [10] and result["status"] == "booked"
    assert result["calendar"]["uid"] == "ktv-10@rezervace.ktv.tul.cz"


def test_sauna_booking_requires_a_gender(tmp_path):
    future = datetime.now(PRAGUE) + timedelta(days=3)
    client = FakeClient([_act(12, "Sauna MUŽI", "SAUNA mužská šatna", future)])
    svc = KTVService(client, cache_dir=tmp_path)
    with pytest.raises(KTVError, match="needs a gender"):
        svc.book(12, Kind.SAUNA)
    assert svc.book(12, Kind.SAUNA, Gender.MALE)["status"] == "booked"
