"""Group challenges (session 27; docs/clubs.md §7): the pure half. Validation of a challenge's configuration, scoring from one member's
own already-filtered activities, and ranking. No I/O, no clock (callers pass `as_of`).

Design stance, because a challenge is a nudge toward training more and must not become a nudge toward training unsafely:

  * Volume is capped three ways: a per-day cap, a per-week ceiling, and a goal the score can never exceed. A challenge with no goal
    is refused (also a CHECK constraint). Extra volume past any of them earns nothing, so there is no way to "win" by overtraining.
  * Consistency rewards weeks that reach a modest target (1-5 sessions), never more; there is no streak metric, and a member can
    excuse a week (no reason stored) so illness or rest is never a penalty.
  * Erg-test participation counts distinct test types attempted, never how fast.
  * Nothing here reads, ranks or even names body weight, calories, recovery, sleep or any health metric; the metric vocabulary has no
    such entry, and tests/test_clubs_privacy.py proves it structurally.
  * The numeric limits are named constants, marked PENDING SAFETY REVIEW (like session 26's minimum-age constants): they are a
    reasonable first position, not coaching or medical advice.

Only provider-sourced activities count (the caller filters; see sync/club_challenges.py). Equal scores share a rank."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

METRICS = ("distance", "time", "sessions", "tests", "consistency")
SPORTS = ("rowing", "any")

# --- PENDING SAFETY REVIEW -------------------------------------------------------------------------------------------
MIN_SESSION_S_FLOOR = 900  # nothing under 15 minutes counts as a session
DEFAULT_MIN_SESSION_S = 1200
MIN_DAYS, MAX_DAYS = 7, 84  # a challenge lasts one to twelve weeks
GRACE_DAYS = 2  # provider syncs lag; standings freeze this long after the end date
DAY_CAP_S = {"adult": 10800, "junior": 7200}  # most time counted from one day
DAY_CAP_M = {"adult": 30000, "junior": 20000}  # most distance counted from one day
WEEK_CEILING_S = {"adult": 12 * 3600, "junior": 8 * 3600}  # most time counted from one week
WEEK_CEILING_M = {"adult": 150000, "junior": 100000}
MAX_SESSIONS_PER_DAY = 2
MAX_SESSIONS_PER_WEEK = 6
TARGET_PER_WEEK_RANGE = (1, 5)
DEFAULT_TARGET_PER_WEEK = 3
TEST_BOARDS_MAX = 7  # lb.BOARDS
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChallengeSpec:
    metric: str
    start: date
    end: date
    goal: Optional[int]
    audience: str = "adult"
    sport: str = "rowing"
    target_per_week: Optional[int] = None
    day_cap_m: Optional[int] = None
    day_cap_s: Optional[int] = None
    min_session_s: int = DEFAULT_MIN_SESSION_S

    @property
    def weeks(self) -> int:
        return len(week_starts(self.start, self.end))


@dataclass(frozen=True)
class Score:
    value: int
    detail: dict
    claimed_keys: tuple[str, ...]  # every provider activity this score relied on, so no other account can count it too


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_starts(start: date, end: date) -> list[date]:
    out, w = [], monday(start)
    while w <= end:
        out.append(w)
        w += timedelta(days=7)
    return out


def phase(spec: ChallengeSpec, today: date) -> str:
    """upcoming | open | grace (ended, standings still settling) | closed (frozen)."""
    if today < spec.start:
        return "upcoming"
    if today <= spec.end:
        return "open"
    return "grace" if today <= spec.end + timedelta(days=GRACE_DAYS) else "closed"


def can_join(spec: ChallengeSpec, today: date) -> bool:
    return today <= spec.end


# ---------------------------------------------------------------- validation

def validate_challenge(*, metric: str, start: date, end: date, goal: Optional[int], audience: str = "adult", sport: str = "rowing",
                       target_per_week: Optional[int] = None, day_cap_m: Optional[int] = None, day_cap_s: Optional[int] = None,
                       min_session_s: Optional[int] = None, today: Optional[date] = None) -> ChallengeSpec:
    """Refuses an unsafe or unscoreable configuration with a message that says what to change."""
    if metric not in METRICS:
        raise ValueError("a challenge measures distance, time trained, number of sessions, erg-test participation or consistency")
    if sport not in SPORTS:
        raise ValueError("sport must be rowing or any")
    aud = "junior" if audience == "junior" else "adult"
    if today and start < today:
        raise ValueError("a challenge can't start in the past")
    days = (end - start).days + 1
    if not (MIN_DAYS <= days <= MAX_DAYS):
        raise ValueError(f"a challenge lasts {MIN_DAYS // 7} to {MAX_DAYS // 7} weeks")
    min_s = DEFAULT_MIN_SESSION_S if min_session_s is None else int(min_session_s)
    if min_s < MIN_SESSION_S_FLOOR:
        raise ValueError(f"a session must be at least {MIN_SESSION_S_FLOOR // 60} minutes to count")
    weeks = len(week_starts(start, end))

    cap_s = DAY_CAP_S[aud] if day_cap_s is None else int(day_cap_s)
    cap_m = DAY_CAP_M[aud] if day_cap_m is None else int(day_cap_m)
    if not (MIN_SESSION_S_FLOOR <= cap_s <= DAY_CAP_S[aud]):
        raise ValueError(f"at most {DAY_CAP_S[aud] // 3600:g} hours a day can count" + (" in a junior club" if aud == "junior" else ""))
    if not (1000 <= cap_m <= DAY_CAP_M[aud]):
        raise ValueError(f"at most {DAY_CAP_M[aud] // 1000} km a day can count" + (" in a junior club" if aud == "junior" else ""))

    goal_v: Optional[int] = None if goal is None else int(goal)
    if metric in ("distance", "time", "sessions") and (goal_v is None or goal_v <= 0):
        raise ValueError("set a goal: a challenge counts up to it and no further, so extra volume never earns more")
    if metric == "distance" and goal_v > WEEK_CEILING_M[aud] * weeks:
        raise ValueError(f"that goal needs more than {WEEK_CEILING_M[aud] // 1000} km a week; choose a smaller one")
    if metric == "time" and goal_v > WEEK_CEILING_S[aud] * weeks:
        raise ValueError(f"that goal needs more than {WEEK_CEILING_S[aud] // 3600} hours a week; choose a smaller one")
    if metric == "sessions" and goal_v > MAX_SESSIONS_PER_WEEK * weeks:
        raise ValueError(f"that goal needs more than {MAX_SESSIONS_PER_WEEK} sessions a week; choose a smaller one")
    if metric == "tests":
        goal_v = TEST_BOARDS_MAX if goal_v is None else goal_v
        if not (1 <= goal_v <= TEST_BOARDS_MAX):
            raise ValueError(f"erg tests count 1-{TEST_BOARDS_MAX} distinct distances or times")
    tpw: Optional[int] = None
    if metric == "consistency":
        tpw = DEFAULT_TARGET_PER_WEEK if target_per_week is None else int(target_per_week)
        if not (TARGET_PER_WEEK_RANGE[0] <= tpw <= TARGET_PER_WEEK_RANGE[1]):
            raise ValueError(f"a week counts with {TARGET_PER_WEEK_RANGE[0]}-{TARGET_PER_WEEK_RANGE[1]} sessions; more earns nothing")
        goal_v = weeks if goal_v is None else min(goal_v, weeks)
    return ChallengeSpec(metric, start, end, goal_v, aud, sport, tpw, cap_m, cap_s, min_s)


def describe(spec: ChallengeSpec) -> list[str]:
    """The rules in plain words, shown on the challenge page: what counts, what doesn't, how ties work."""
    what = {
        "distance": f"Distance counts up to {spec.goal / 1000:g} km in total.",
        "time": f"Time trained counts up to {spec.goal / 3600:g} hours in total.",
        "sessions": f"Sessions count up to {spec.goal}.",
        "tests": f"Each different erg test you complete counts once (up to {spec.goal}). Speed is never scored.",
        "consistency": f"A week counts when you complete {spec.target_per_week} session(s) of at least {spec.min_session_s // 60} minutes; extra sessions earn nothing.",
    }[spec.metric]
    rules = [what]
    if spec.metric in ("distance", "time"):
        week = WEEK_CEILING_M[spec.audience] // 1000 if spec.metric == "distance" else WEEK_CEILING_S[spec.audience] // 3600
        day = f"{spec.day_cap_m // 1000} km" if spec.metric == "distance" else f"{spec.day_cap_s / 3600:g} hours"
        rules.append(f"No more than {day} a day and {week}{' km' if spec.metric == 'distance' else ' hours'} a week can count, so training harder than that earns nothing extra.")
    if spec.metric in ("time", "sessions", "consistency"):
        rules.append(f"A session must last at least {spec.min_session_s // 60} minutes to count.")
    if spec.metric == "sessions":
        rules.append(f"At most {MAX_SESSIONS_PER_DAY} sessions a day and {MAX_SESSIONS_PER_WEEK} a week count.")
    if spec.metric == "consistency":
        rules.append("You can excuse any week (for illness, rest or travel) without giving a reason; an excused week isn't counted against you.")
    sport = "Only rowing sessions count." if spec.sport == "rowing" else "Any recorded sport counts."
    rules += [
        sport,
        "Only activities recorded by a connected source (Garmin, Concept2, Whoop) count: typed-in or edited results don't. Each activity counts once, for one account.",
        "Equal scores share a rank (1, 2, 2, 4). There is no hidden tie-break.",
        f"Joining is open until the end date. Standings settle {GRACE_DAYS} days after the end, then freeze.",
        "Nothing about weight, calories, recovery or sleep is used or shown.",
    ]
    return rules


# ---------------------------------------------------------------- scoring

def _qualifying(spec: ChallengeSpec, acts: Iterable[dict]) -> list[dict]:
    """Activities in the window that match the sport and (except for tests) the minimum length, in a stable order. Defensive about
    flags even though the caller filters: excluded, absorbed and non-provider rows never count."""
    out = []
    for a in acts:
        if a.get("excluded") or a.get("absorbed") or not a.get("provider_sourced", True):
            continue
        if not (spec.start <= a["date"] <= spec.end):
            continue
        if spec.sport == "rowing" and a.get("sport_family") != "rowing":
            continue
        if spec.metric != "tests" and (a.get("duration_s") or 0) < spec.min_session_s:
            continue
        out.append(a)
    return sorted(out, key=lambda a: (a.get("start") or datetime.combine(a["date"], datetime.min.time()), a["key"]))


def _capped_sum(spec: ChallengeSpec, qual: list[dict], measure: str) -> tuple[int, list[str]]:
    """Sum of `measure` with the per-day cap then the per-week ceiling applied in time order."""
    day_cap = spec.day_cap_s if measure == "duration_s" else spec.day_cap_m
    week_cap = (WEEK_CEILING_S if measure == "duration_s" else WEEK_CEILING_M)[spec.audience]
    day_used: dict[date, float] = {}
    week_used: dict[date, float] = {}
    total, keys = 0.0, []
    for a in qual:
        raw = float(a.get(measure) or 0)
        if raw <= 0:
            continue
        d, w = a["date"], monday(a["date"])
        take = min(raw, day_cap - day_used.get(d, 0.0), week_cap - week_used.get(w, 0.0))
        if take <= 0:
            continue
        day_used[d] = day_used.get(d, 0.0) + take
        week_used[w] = week_used.get(w, 0.0) + take
        total += take
        keys.append(a["key"])
    return int(total), keys


def _capped_count(qual: list[dict]) -> tuple[int, list[str]]:
    per_day: dict[date, int] = {}
    per_week: dict[date, int] = {}
    keys = []
    for a in qual:
        d, w = a["date"], monday(a["date"])
        if per_day.get(d, 0) >= MAX_SESSIONS_PER_DAY or per_week.get(w, 0) >= MAX_SESSIONS_PER_WEEK:
            continue
        per_day[d] = per_day.get(d, 0) + 1
        per_week[w] = per_week.get(w, 0) + 1
        keys.append(a["key"])
    return len(keys), keys


def score(spec: ChallengeSpec, activities: Iterable[dict], *, as_of: date, excused_weeks: Iterable[date] = ()) -> Score:
    """One member's standing from their own activities. Pure: the same inputs always give the same score, and no input is a
    health metric (activity dicts carry date/start/duration/distance/sport/provider flags and a board key, nothing else)."""
    qual = _qualifying(spec, activities)
    if spec.metric == "distance":
        total, keys = _capped_sum(spec, qual, "distance_m")
        return Score(min(total, spec.goal), {"counted_m": min(total, spec.goal), "goal_m": spec.goal, "reached": total >= spec.goal}, tuple(keys))
    if spec.metric == "time":
        total, keys = _capped_sum(spec, qual, "duration_s")
        return Score(min(total, spec.goal), {"counted_s": min(total, spec.goal), "goal_s": spec.goal, "reached": total >= spec.goal}, tuple(keys))
    if spec.metric == "sessions":
        n, keys = _capped_count(qual)
        return Score(min(n, spec.goal), {"counted": min(n, spec.goal), "goal": spec.goal, "reached": n >= spec.goal}, tuple(keys))
    if spec.metric == "tests":
        seen: dict[str, str] = {}
        for a in qual:
            board = a.get("board_key")
            if board and board not in seen:
                seen[board] = a["key"]
        n = min(len(seen), spec.goal)
        return Score(n, {"counted": n, "goal": spec.goal, "boards": sorted(seen)}, tuple(seen.values()))
    # consistency
    excused = {monday(d) for d in excused_weeks}
    per_week: dict[date, int] = {}
    for a in qual:
        per_week[monday(a["date"])] = per_week.get(monday(a["date"]), 0) + 1
    met, eligible, rows = 0, 0, []
    for w in week_starts(spec.start, spec.end):
        if w > as_of:
            break
        done = per_week.get(w, 0) >= spec.target_per_week
        ended = (w + timedelta(days=6)) < as_of or as_of > spec.end
        if w in excused:
            rows.append({"week": w.isoformat(), "state": "excused"})
            continue
        if done or ended:
            eligible += 1
            met += 1 if done else 0
            rows.append({"week": w.isoformat(), "state": "met" if done else "missed", "sessions": per_week.get(w, 0)})
        else:
            rows.append({"week": w.isoformat(), "state": "in_progress", "sessions": per_week.get(w, 0)})
    rate = (10000 * met // eligible) if eligible else 0
    return Score(rate, {"met": met, "eligible_weeks": eligible, "target_per_week": spec.target_per_week, "weeks": rows}, tuple(a["key"] for a in qual))


def format_value(spec: ChallengeSpec, value: int, detail: Optional[dict] = None) -> str:
    if spec.metric == "distance":
        return f"{value / 1000:,.1f} km"
    if spec.metric == "time":
        h, m = divmod(value // 60, 60)
        return f"{h}h {m:02d}m"
    if spec.metric == "sessions":
        return f"{value} session{'' if value == 1 else 's'}"
    if spec.metric == "tests":
        return f"{value} test{'' if value == 1 else 's'}"
    if detail and detail.get("eligible_weeks") is not None:
        return f"{detail['met']} of {detail['eligible_weeks']} weeks"
    return f"{value / 100:.0f}% of weeks"


# ---------------------------------------------------------------- ranking

def activity_key(secret: str, source: str, external_id: str) -> str:
    """Keyed hash of a provider activity (claims table): one real activity can't count for two accounts, and the table never holds a provider id."""
    import hmac

    return hmac.new(secret.encode(), f"{source}:{external_id}".encode(), hashlib.sha256).hexdigest()[:40]


def rank_standings(rows: Iterable[dict], challenge_id: int) -> list[dict]:
    """Standard competition ranking (1, 2, 2, 4) on `value`, highest first. Tied members share a rank; the order *within* a tie is a
    per-challenge hash, so nothing implies one is ahead (no date, no join order, no name)."""
    def tie(r: dict) -> str:
        return hashlib.sha256(f"{challenge_id}:{r['owner_id']}".encode()).hexdigest()

    ordered = sorted(rows, key=lambda r: (-r["value"], tie(r)))
    out, prev, rank = [], None, 0
    for i, r in enumerate(ordered, start=1):
        if r["value"] != prev:
            rank, prev = i, r["value"]
        out.append({**r, "rank": rank})
    return out
