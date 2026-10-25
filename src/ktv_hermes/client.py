"""HTTP client for rezervace.ktv.tul.cz (Nette app, session-cookie login)."""

from __future__ import annotations

import time
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin

import certifi
import requests

from .models import Activity
from .parser import EnrollForm, flash_messages, is_logged_in, parse_enroll_form, parse_week

BASE_URL = "https://rezervace.ktv.tul.cz"
USER_AGENT = "ktv-hermes/0.1 (+https://github.com/tomyjany/hermes-tul-ktv)"


class KTVError(RuntimeError):
    pass


class AuthError(KTVError):
    pass


def _ca_bundle() -> str:
    """certifi roots + the GEANT intermediate the server fails to send (incomplete chain)."""
    cache = Path.home() / ".cache" / "ktv-hermes"
    cache.mkdir(parents=True, exist_ok=True)
    bundle = cache / "ca-bundle.pem"
    intermediate = resources.files("ktv_hermes").joinpath("certs/geant-tls-rsa-1.pem").read_text()
    content = Path(certifi.where()).read_text() + "\n" + intermediate
    if not bundle.exists() or bundle.read_text() != content:
        bundle.write_text(content)
    return str(bundle)


class KTVClient:
    def __init__(self, username: str, password: str, *, base_url: str = BASE_URL, timeout: float = 30.0):
        if not username or not password:
            raise AuthError("KTV_USERNAME and KTV_PASSWORD must be set")
        self.username = username
        self._password = password
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.verify = _ca_bundle()
        self._logged_in = False

    # ---- low level -------------------------------------------------------
    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        resp = self.session.request(method, self._url(path), timeout=self.timeout, **kw)
        resp.raise_for_status()
        return resp

    def login(self) -> None:
        self._request("GET", "/")
        resp = self._request(
            "POST",
            "/",
            data={"email": self.username, "password": self._password, "_do": "signForm-signForm-submit"},
        )
        if not is_logged_in(resp.text):
            msgs = flash_messages(resp.text)
            raise AuthError("KTV login failed" + (f": {'; '.join(msgs)}" if msgs else ""))
        # Show every area so personal history isn't filtered to one building.
        self._request("POST", "/asc", data={"area": "all", "_do": "ascCalendarComponent-areaFilter-submit"})
        self._logged_in = True

    def _get_page(self, path: str, params: dict | None = None) -> str:
        if not self._logged_in:
            self.login()
        resp = self._request("GET", path, params=params)
        if not is_logged_in(resp.text):
            self.login()
            resp = self._request("GET", path, params=params)
        return resp.text

    # ---- calendar --------------------------------------------------------
    def week(self, year: int, week: int) -> list[Activity]:
        html = self._get_page(
            "/asc", {"ascCalendarComponent-year": year, "ascCalendarComponent-week": week}
        )
        return parse_week(html, year, week)

    def activities_between(self, start: date, end: date, *, delay: float = 0.0) -> list[Activity]:
        """Activities whose start date lies in [start, end], scanning ISO weeks."""
        out: list[Activity] = []
        monday = start - timedelta(days=start.weekday())
        while monday <= end:
            iso = monday.isocalendar()
            for act in self.week(iso.year, iso.week):
                if start <= act.start.date() <= end:
                    out.append(act)
            monday += timedelta(days=7)
            if delay and monday <= end:
                time.sleep(delay)
        return out

    def find_activity(self, activity_id: int) -> Activity:
        """Locate an activity in the weekly calendar (the modal alone lacks occupancy/kind context)."""
        form = self.enroll_form(activity_id)
        if form.start is None:
            raise KTVError(f"activity {activity_id} has no date in its detail")
        day = form.start.date()
        for act in self.activities_between(day, day):
            if act.activity_id == activity_id:
                return act
        raise KTVError(f"activity {activity_id} not found in the calendar on {day}")

    # ---- enroll / cancel -------------------------------------------------
    def enroll_form(self, activity_id: int) -> EnrollForm:
        if not self._logged_in:
            self.login()
        resp = self._request(
            "GET",
            "/asc",
            params={"ascCalendarComponent-activityId": activity_id, "do": "ascCalendarComponent-enroll"},
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        snippets = (resp.json().get("snippets") or {}) if "json" in resp.headers.get("content-type", "") else {}
        snippet = next((v for k, v in snippets.items() if "enrollForm" in k), None)
        if not snippet:
            raise KTVError(f"no enroll form returned for activity {activity_id}")
        return parse_enroll_form(snippet)

    def _submit(self, activity_id: int, button: dict[str, str], want_enrolled: bool) -> tuple[EnrollForm, list[str]]:
        form = self.enroll_form(activity_id)
        if form.enrolled == want_enrolled:
            return form, ["already " + ("enrolled" if want_enrolled else "not enrolled")]
        if want_enrolled and not form.can_enroll:
            raise KTVError(f"activity {activity_id} cannot be booked (no enroll button: full, past or closed)")
        resp = self._request("POST", form.action, data={**form.fields, **button})
        messages = flash_messages(resp.text)
        after = self.enroll_form(activity_id)
        if after.enrolled != want_enrolled:
            verb = "book" if want_enrolled else "cancel"
            raise KTVError(f"failed to {verb} activity {activity_id}" + (f": {'; '.join(messages)}" if messages else ""))
        return after, messages

    def enroll(self, activity_id: int) -> tuple[EnrollForm, list[str]]:
        return self._submit(activity_id, {"_submit": "Přihlásit"}, True)

    def cancel(self, activity_id: int) -> tuple[EnrollForm, list[str]]:
        return self._submit(activity_id, {"optOut": "Odhlásit"}, False)
