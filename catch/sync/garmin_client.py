from __future__ import annotations

import base64
import json
import logging
import shutil
import zipfile
from datetime import date as date_, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlmodel import Session

from catch.core import security
from catch.core.config import settings
from catch.core.models import OAuthToken
from catch.sync.canonical import resolve_canonical
from catch.sync.fit_parse import parse_fit
from catch.sync.samples import store_samples_from_fit
from catch.sync.upsert import upsert_activity, upsert_body_comp, upsert_daily_wellness

logger = logging.getLogger("catch.garmin")

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_URL = f"{BASE_URL}/personalapitoken-service/personal-api/personal-api-key/token"
SOURCE = "garmin"


class GarminAuthError(RuntimeError):
    pass


class GarminClient:
    def __init__(self, session: Session, http: httpx.Client | None = None):
        self.db = session
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=30.0)

    # -- auth -----------------------------------------------------------

    def _cached_token(self) -> OAuthToken | None:
        return self.db.get(OAuthToken, SOURCE)

    def _exchange_token(self) -> str:
        if not settings.garmin_api_key:
            raise GarminAuthError("GARMIN_PERSONAL_API_KEY is not set")
        resp = httpx.post(
            TOKEN_URL,
            headers={"Authorization": f"ApiKey {settings.garmin_api_key}"},
            timeout=30.0,
        )
        if resp.status_code == 401:
            raise GarminAuthError("Garmin key expired, create a new one")
        resp.raise_for_status()
        # The token endpoint returns the bearer token itself as a raw JWT, Content-Type
        # text/plain — not a JSON envelope. Confirmed against a live response; the JWT's
        # own `exp` claim gives us the real expiry (observed: exactly 24h after `iat`).
        token = resp.text.strip()
        expires_at = _jwt_expiry(token) or (datetime.now(timezone.utc) + timedelta(hours=23))

        row = self._cached_token()
        if row is None:
            row = OAuthToken(source=SOURCE, access_token_enc=security.encrypt(token))
            self.db.add(row)
        row.access_token_enc = security.encrypt(token)
        row.expires_at = expires_at
        row.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return token

    def _token(self) -> str:
        row = self._cached_token()
        if row and row.expires_at and row.expires_at - timedelta(hours=1) > datetime.now(timezone.utc):
            return security.decrypt(row.access_token_enc)
        return self._exchange_token()

    # -- low level --------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        token = self._token()
        resp = self.http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401:
            raise GarminAuthError("Garmin key expired, create a new one")
        resp.raise_for_status()
        return resp

    # -- activities ---------------------------------------------------------

    def list_activities(self, start_date: date_, end_date: date_, page_size: int = 50) -> Iterable[dict]:
        start = 0
        while True:
            resp = self._get(
                "/activitylist-service/activities/search/activities",
                params={
                    "start": start,
                    "limit": page_size,
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                },
            )
            page = resp.json()
            if not page:
                return
            for item in page:
                yield item
            if len(page) < page_size:
                return
            start += page_size

    def download_fit(self, activity_id: int, dest_dir: Path) -> Path | None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dest_dir / f"{activity_id}.zip"
        token = self._token()
        with self.http.stream(
            "GET",
            f"/download-service/files/activity/{activity_id}",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status_code == 401:
                raise GarminAuthError("Garmin key expired, create a new one")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        fit_path = None
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".fit"):
                    extracted = dest_dir / f"{activity_id}.fit"
                    with zf.open(name) as src, open(extracted, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    fit_path = extracted
                    break
        zip_path.unlink(missing_ok=True)
        return fit_path

    def sync_activities(self, start_date: date_, end_date: date_, fit_dir: Path) -> int:
        count = 0
        for item in self.list_activities(start_date, end_date):
            activity_id = item.get("activityId")
            if activity_id is None:
                continue
            activity_type = item.get("activityType")
            type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else activity_type
            start_raw = item.get("startTimeGMT")
            start_dt = _parse_datetime(start_raw)
            row = upsert_activity(
                self.db,
                source=SOURCE,
                external_id=str(activity_id),
                type=type_key,
                start=start_dt,
                duration=item.get("duration"),
                distance=item.get("distance"),
                avg_hr=item.get("averageHR"),
                max_hr=item.get("maxHR"),
                avg_power=item.get("avgPower"),
                calories=item.get("calories"),
                steps=item.get("steps"),
                bmr_kcal=item.get("bmrCalories"),
                title_hint=item.get("activityName"),
                raw_json=json.dumps(item),
            )
            if not row.fit_path or not Path(row.fit_path).exists():
                # A stored fit_path can go stale without ever being cleared: a DB migrated
                # from the laptop to the Pi (deploy/pi-bootstrap.sh adopting a staged catch.db
                # + fit/ dir) carries laptop-relative paths like "data/fit/X.fit" that don't
                # resolve under the Pi's WorkingDirectory. If the bootstrap already copied the
                # file into this run's fit_dir, just re-point to it instead of re-hitting
                # Garmin's API.
                expected = fit_dir / f"{activity_id}.fit"
                if expected.exists():
                    fit_path = expected
                else:
                    try:
                        fit_path = self.download_fit(activity_id, fit_dir)
                    except (httpx.HTTPStatusError, httpx.TransportError):
                        # A single activity's FIT download failing (rate limit, transient network
                        # error) must not abort every later window in a multi-month backfill —
                        # confirmed a real risk live (a 429 on one activity used to kill the whole
                        # backfill.run, discarding months of otherwise-successful history). Leaving
                        # fit_path unset means the next sync/backfill retries exactly this activity.
                        logger.warning("FIT download failed for activity %s, will retry on next sync", activity_id, exc_info=True)
                        fit_path = None
                if fit_path:
                    row.fit_path = str(fit_path)
                    self.db.add(row)
                    self.db.commit()
            if row.fit_path:
                self._ingest_fit_samples(row)
                self._ingest_track(row)
            resolve_canonical(self.db, row.canonical_id)
            count += 1
        return count

    def _ingest_fit_samples(self, row) -> None:
        """Parses the FIT file once per activity (origin/HR-source detection, Part A/E's
        per-sample zones/strain) — skipped on every later re-sync once samples already
        exist, since a FIT file never changes after the activity is recorded."""
        from catch.core.models import ActivitySamples

        if self.db.get(ActivitySamples, row.id) is not None:
            return
        fit_samples = parse_fit(row.fit_path)
        if fit_samples is None:
            return
        row.origin = "peloton" if fit_samples.is_peloton_like else "watch"
        row.hr_source_type = fit_samples.hr_source_type
        if fit_samples.is_peloton_like:
            # Part B.2: "map Just Ride and class rides to cycling (indoor)" regardless of
            # whatever Garmin typed the import as — sport_family is set at upsert time, before
            # this FIT-level Peloton detection runs, from the summary's typeKey alone. No real
            # Peloton-pushed activity exists in this account to confirm what typeKey Garmin
            # assigns it (docs/peloton.md), so this is the one place that can't just trust it.
            row.sport_family = "cycling"
        if fit_samples.laps:
            row.laps_json = json.dumps(fit_samples.laps)
        if row.avg_cadence is None and any(v is not None for v in fit_samples.cadence):
            defined = [v for v in fit_samples.cadence if v is not None]
            row.avg_cadence = sum(defined) / len(defined)
        self.db.add(row)
        self.db.commit()
        store_samples_from_fit(self.db, row.id, fit_samples)

    def _ingest_track(self, row) -> None:
        """Session 20: the GPS track, parsed once per activity in its own pass. Isolated so a
        GPS bug can never break the HR/strain ingest above or abort the sync."""
        try:
            from catch.sync.tracks import ingest_track

            ingest_track(self.db, row)
        except Exception:
            logger.warning("GPS track ingest failed for activity %s", row.external_id, exc_info=True)
            self.db.rollback()

    # -- health -------------------------------------------------------------

    def sync_health(self, start_date: date_, end_date: date_) -> int:
        count = 0
        count += self._sync_sleep(start_date, end_date)
        count += self._sync_hrv(start_date, end_date)
        count += self._sync_usersummary(start_date, end_date)
        return count

    def _sync_sleep(self, start_date: date_, end_date: date_) -> int:
        resp = self._get(
            "/sleep-service/sleep/dailySleepSummariesByDate",
            params={"startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
        )
        items = resp.json() or []
        n = 0
        for item in items:
            day = _parse_date(item.get("calendarDate"))
            if day is None:
                continue
            sleep_scores = item.get("sleepScores")
            sleep_score = None
            if isinstance(sleep_scores, dict):
                overall = sleep_scores.get("overall")
                if isinstance(overall, dict):
                    sleep_score = overall.get("value")
            upsert_daily_wellness(
                self.db,
                day,
                sleep_seconds=item.get("sleepTimeSeconds"),
                deep_sleep_seconds=item.get("deepSleepSeconds"),
                light_sleep_seconds=item.get("lightSleepSeconds"),
                rem_sleep_seconds=item.get("remSleepSeconds"),
                awake_sleep_seconds=item.get("awakeSleepSeconds"),
                sleep_score=sleep_score,
                # Session 15 (see PLAN.md Part B): sleep-period respiration, distinct from
                # the whole-day `respiration` column (already filled from a different
                # endpoint, see _sync_usersummary) — the illness early-warning signal wants
                # the overnight value specifically.
                sleep_respiration_avg=item.get("averageRespirationValue"),
                wake_time_minutes=_local_minutes_of_day(item.get("sleepEndTimestampLocal")),
            )
            n += 1
        return n

    def _sync_hrv(self, start_date: date_, end_date: date_) -> int:
        resp = self._get(
            f"/hrv-service/hrv/daily/{start_date.isoformat()}/{end_date.isoformat()}",
        )
        data = resp.json() or {}
        items = data.get("hrvSummaries") or []
        n = 0
        for item in items:
            day = _parse_date(item.get("calendarDate"))
            if day is None:
                continue
            upsert_daily_wellness(self.db, day, hrv_rmssd=item.get("lastNightAvg"))
            n += 1
        return n

    def _sync_usersummary(self, start_date: date_, end_date: date_) -> int:
        # The OpenAPI spec types this response loosely; the real shape (confirmed against a
        # live call) nests each day's metrics under heartRate/stress/bodyBattery/respiration/
        # pulseOx/movement/calories/intensityMinutes objects, not flat fields. This is also
        # where whole-day (not just sleep-period) SpO2 and respiration come from.
        resp = self._get(
            "/usersummary-service/v2/dailysummaries",
            params={"startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
        )
        data = resp.json() or {}
        items = data.get("data") or []
        n = 0
        for item in items:
            day = _parse_date(item.get("calendarDate"))
            if day is None:
                continue
            heart_rate = item.get("heartRate") or {}
            stress = item.get("stress") or {}
            body_battery = item.get("bodyBattery") or {}
            respiration = item.get("respiration") or {}
            pulse_ox = item.get("pulseOx") or {}
            # Session 13 (see PLAN.md Part A): daily steps/calories/intensity minutes/floors,
            # confirmed in the real recorded fixture (tests/fixtures/garmin/
            # usersummary_range.json) though unused until now. Fractional floor `value`s are
            # already floored by Garmin per the schema's own description.
            movement = item.get("movement") or {}
            calories = item.get("calories") or {}
            intensity = item.get("intensityMinutes") or {}
            steps = movement.get("steps") or {}
            floors_up = movement.get("floorsAscended") or {}
            floors_down = movement.get("floorsDescended") or {}
            upsert_daily_wellness(
                self.db,
                day,
                resting_hr=heart_rate.get("restingValue"),
                stress=stress.get("avgLevel"),
                body_battery=body_battery.get("latestValue"),
                spo2=pulse_ox.get("avgValue"),
                respiration=respiration.get("avgValue"),
                steps=steps.get("value"),
                active_kcal=calories.get("burnedActive"),
                total_kcal=calories.get("burnedTotal"),
                bmr_kcal=calories.get("burnedResting"),
                moderate_intensity_minutes=intensity.get("moderate"),
                vigorous_intensity_minutes=intensity.get("vigorous"),
                floors_climbed=floors_up.get("value"),
                floors_descended=floors_down.get("value"),
            )
            n += 1
        return n

    # -- body composition (task Part D) --------------------------------------------------

    def sync_weight(self, start_date: date_, end_date: date_) -> int:
        """`/weight-service/weight/range` — confirmed live (docs/garmin-endpoints.md):
        `weight` is in GRAMS despite the OpenAPI schema claiming kilograms. `bodyFat` maps to
        `fat_pct`; `muscleMass`/`boneMass`/`bodyWater` are left unmapped (every real entry in
        this account has them null, so there's nothing to confirm their unit against)."""
        resp = self._get(f"/weight-service/weight/range/{start_date.isoformat()}/{end_date.isoformat()}")
        data = resp.json() or {}
        n = 0
        for summary in data.get("dailyWeightSummaries") or []:
            entries = summary.get("allWeightMetrics") or []
            if not entries and summary.get("latestWeight"):
                entries = [summary["latestWeight"]]
            for entry in entries:
                weight_g = entry.get("weight")
                if weight_g is None:
                    continue
                ts = _parse_epoch_ms(entry.get("timestampGMT") or entry.get("date"))
                if ts is None:
                    continue
                sample_pk = entry.get("samplePk")
                upsert_body_comp(
                    self.db,
                    source="garmin",
                    external_id=str(sample_pk) if sample_pk is not None else ts.isoformat(),
                    ts=ts,
                    weight_kg=weight_g / 1000.0,
                    fat_pct=entry.get("bodyFat"),
                )
                n += 1
        return n

    def _call_with_backoff(self, label: str, fn, *args) -> int:
        """A long backfill makes many sequential Garmin calls — a 429 partway through must
        not abort every later window (the same risk `sync_activities` already guards per-FIT-
        download, generalized here to every per-window call). One retry after a short sleep
        on a 429 specifically; any other failure, or a 429 that persists, is logged and
        treated as 0 for this window rather than raised."""
        import time

        for attempt in range(2):
            try:
                return fn(*args)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt == 0:
                    logger.warning("%s rate-limited (429), backing off before one retry", label)
                    time.sleep(10)
                    continue
                logger.warning("%s failed for window %s-%s, skipping this window", label, args[0], args[1], exc_info=True)
                return 0
            except httpx.TransportError:
                logger.warning("%s failed for window %s-%s, skipping this window", label, args[0], args[1], exc_info=True)
                return 0
        return 0

    def backfill(self, days: int, fit_dir: Path, window_days: int = 30) -> dict[str, int]:
        end_date = date_.today()
        start_date = end_date - timedelta(days=days)
        totals = {"activities": 0, "health_rows": 0, "weight_rows": 0}
        cursor = start_date
        while cursor <= end_date:
            window_end = min(cursor + timedelta(days=window_days), end_date)
            totals["health_rows"] += self._call_with_backoff("sync_health", self.sync_health, cursor, window_end)
            totals["activities"] += self._call_with_backoff("sync_activities", self.sync_activities, cursor, window_end, fit_dir)
            totals["weight_rows"] += self._call_with_backoff("sync_weight", self.sync_weight, cursor, window_end)
            cursor = window_end + timedelta(days=1)
        return totals


def _jwt_expiry(token: str) -> datetime | None:
    try:
        _, payload_b64, _ = token.split(".")
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except Exception:
        return None


def _parse_date(value: Any) -> date_ | None:
    if not value:
        return None
    if isinstance(value, date_):
        return value
    try:
        return date_.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_epoch_ms(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _local_minutes_of_day(value: Any) -> int | None:
    """Garmin's `*TimestampLocal` fields (unlike `*TimestampGMT`) are epoch-ms that encode
    local wall-clock time *as if* it were UTC — there's no real UTC instant in them, so
    `_parse_epoch_ms` happens to do exactly the right parse here (attaching a bogus UTC
    tzinfo is harmless since only `.hour`/`.minute` are read back out)."""
    dt = _parse_epoch_ms(value)
    return dt.hour * 60 + dt.minute if dt else None


def _parse_datetime(value: Any) -> datetime | None:
    # startTimeGMT is, as the name says, already UTC — attach tzinfo rather than storing naive.
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
