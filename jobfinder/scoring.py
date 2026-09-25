"""Scoring: is this job a fit, is it real, is it fresh, and does it pay?

score = fit + freshness - ghost_risk - pay/knockout penalties, then bucketed.
Every point added or removed leaves a human-readable reason on the job.
"""
from __future__ import annotations

import re
from functools import lru_cache
from datetime import datetime, timezone

from .config import Profile
from .models import Job

# ---------------------------------------------------------------- location
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia", "PR": "Puerto Rico",
}
_STATE_NAME = re.compile(r"\b(" + "|".join(sorted(US_STATES.values(), key=len, reverse=True)) + r")\b", re.I)
_STATE_ABBR = re.compile(r"(?:,\s*|\bUS[A]?\s*[-,]\s*|\b)(" + "|".join(US_STATES) + r")\b(?!\.\w)")
_US = re.compile(r"\b(united states|u\.s\.a?\.?|usa|us-remote|remote[- ,(]*us|us remote|nationwide)\b|^us\b", re.I)
_FOREIGN = re.compile(
    r"\b(canada|ontario|quebec|toronto|montreal|vancouver|mexico|brazil|argentina|colombia|costa rica|chile|"
    r"united kingdom|\buk\b|england|scotland|ireland|dublin|galway|london|germany|deutschland|france|paris|"
    r"netherlands|belgium|switzerland|austria|italy|spain|portugal|poland|czech|hungary|romania|sweden|"
    r"denmark|norway|finland|israel|india|bangalore|bengaluru|hyderabad|pune|chennai|china|shanghai|beijing|"
    r"suzhou|shenzhen|japan|tokyo|korea|seoul|singapore|malaysia|penang|philippines|vietnam|thailand|"
    r"australia|sydney|melbourne|new zealand|taiwan|hong kong|south africa|dominican republic|puerto rico|"
    r"european union|emea|apac|latam)\b", re.I)
# states with pay-transparency laws in effect (a range must appear in the posting)
PAY_TRANSPARENCY = {"CA", "CO", "WA", "NY", "IL", "MN", "MD", "HI", "MA", "VT", "NJ", "DC", "ME", "VA"}


def location_states(loc: str) -> set[str]:
    found = set()
    for m in _STATE_NAME.finditer(loc):
        name = m.group(1).lower()
        for ab, full in US_STATES.items():
            if full.lower() == name:
                found.add(ab)
    for m in _STATE_ABBR.finditer(loc):
        found.add(m.group(1).upper())
    # "Washington" alone is ambiguous with DC but both are US - fine.
    return found


def is_us(job: Job) -> bool | None:
    country = (job.extra.get("country") or "").lower()
    if country:
        if country in ("us", "usa", "united states", "united states of america"):
            return True
        if len(country) <= 3 or "united states" not in country:
            return False
    loc = job.location or ""
    if not loc.strip():
        return None
    if _US.search(loc) or location_states(loc):
        return True
    if _FOREIGN.search(loc):
        return False
    if re.fullmatch(r"\s*(remote|anywhere|hybrid|multiple locations|\d+ locations)\s*", loc, re.I):
        return None
    return None


# ---------------------------------------------------------------- experience
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "zero": 0}
_YEARS = re.compile(
    r"(?P<a>\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:\+|plus)?\s*"
    r"(?:(?:-|–|to)\s*(?P<b>\d{1,2})\s*\+?\s*)?(?:\(\d+\)\s*)?years?", re.I)
_MASTERS = re.compile(r"\b(master'?s?|m\.s\.?|ms|m\.eng|msc|graduate degree|advanced degree)\b", re.I)
_BACHELORS = re.compile(r"\b(bachelor'?s?|b\.s\.?|bs|b\.a\.?|ba|undergraduate)\b", re.I)
_PHD = re.compile(r"\b(ph\.?d|doctorate|doctoral)\b", re.I)


def years_required(text: str) -> tuple[int | None, str]:
    """Best guess at the years of experience required *for someone with an MS*.

    Returns (years, snippet). None when the posting doesn't say.
    Handles "BS + 2 years or MS + 0 years", "3-5 years", "minimum of 5 years", etc.
    """
    if not text:
        return None, ""
    candidates: list[tuple[int, str, str]] = []  # (years, degree_tag, snippet)
    for m in _YEARS.finditer(text):
        start, end = m.start(), m.end()
        after = text[end:end + 70].lower()
        before = text[max(0, start - 110):start]
        near = before.lower() + " " + after
        if not re.search(r"experience|industry|relevant|related|working|in (a|the)|medical|regulated", near):
            continue
        if re.search(r"^\s*(old|of age|warranty|history|ago)", after):
            continue
        a = m.group("a").lower()
        years = _NUM_WORDS.get(a, None) if not a.isdigit() else int(a)
        if years is None or years > 20:
            continue
        # degree mentioned closest before the number wins
        tag = ""
        spans = [(x.end(), "phd") for x in _PHD.finditer(before)] + \
                [(x.end(), "ms") for x in _MASTERS.finditer(before)] + \
                [(x.end(), "bs") for x in _BACHELORS.finditer(before)]
        if spans:
            tag = max(spans)[1]
        candidates.append((years, tag, text[max(0, start - 60):end + 40].replace("\n", " ").strip()))
    if not candidates:
        return None, ""
    ms = [c for c in candidates if c[1] == "ms"]
    if ms:
        best = min(ms)
    else:
        non_phd = [c for c in candidates if c[1] != "phd"] or candidates
        best = min(non_phd)
        if best[1] == "bs" and best[0] >= 1:  # MS usually substitutes ~2 yrs of BS experience
            return max(0, best[0] - 2), best[2]
    return best[0], best[2]


# ---------------------------------------------------------------- salary
_MONEY = re.compile(
    r"\$\s?(?P<a>\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d+)?)\s*(?P<ak>[kK]\b)?"
    r"(?:\s*(?:-|–|—|to)\s*\$?\s?(?P<b>\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d+)?)\s*(?P<bk>[kK]\b)?)?"
    r"(?P<per>\s*(?:/|per|an|a)\s*(?:hour|hr|year|yr|annum|annually))?", re.I)


def parse_salary(text: str) -> tuple[float | None, float | None, str]:
    """Return (low, high) annualized USD and the matched snippet."""
    best = None
    for m in _MONEY.finditer(text or ""):
        def num(g, k):
            if not g:
                return None
            v = float(g.replace(",", ""))
            return v * 1000 if k else v
        lo, hi = num(m.group("a"), m.group("ak")), num(m.group("b"), m.group("bk") or m.group("ak"))
        per = (m.group("per") or "").lower()
        ctx = text[m.end():m.end() + 25].lower()
        hourly = "hour" in per or "hr" in per or "hour" in ctx or (lo is not None and lo < 200 and (hi or lo) < 200)
        if hourly:
            if lo is None or lo < 12 or lo > 200:
                continue
            lo, hi = lo * 2080, (hi * 2080 if hi else None)
        elif lo is None or lo < 25000 or lo > 600000:
            continue
        if hi is not None and (hi < lo or hi > 1_000_000):
            hi = None
        snippet = " ".join(text[m.start():m.end()].split())
        if best is None or (hi and not best[1]):
            best = (lo, hi, snippet)
    return best if best else (None, None, "")


# ---------------------------------------------------------------- helpers
@lru_cache(maxsize=4096)
def _rx(pattern: str) -> re.Pattern:
    # Text is lowercased before matching; IGNORECASE is ~2.5x slower, so only use it
    # when a pattern contains an uppercase literal (e.g. a user-added pattern).
    needs_i = re.search(r"(?<!\\)[A-Z]", pattern) is not None
    return re.compile(pattern, re.I if needs_i else 0)


def _any(patterns: list[str], text: str) -> list[str]:
    """Patterns (from profile.toml) that match `text`. Pass lowercased text."""
    return [p for p in patterns if _rx(p).search(text)]


def days_old(job: Job, now: datetime) -> float | None:
    ref = job.posted_at or job.first_seen
    if ref is None:
        return None
    return max(0.0, (now - ref).total_seconds() / 86400)


# ---------------------------------------------------------------- main entry
def title_matches(profile: Profile, title: str) -> bool:
    t = title.lower()
    if _any(profile.title_exclude, t):
        return False
    return bool(_any(profile.title_primary, t) or _any(profile.title_secondary, t))


def score_job(job: Job, p: Profile, now: datetime | None = None) -> Job:
    now = now or datetime.now(timezone.utc)
    title = job.title.lower()
    text = f"{job.title}\n{job.description}"
    low = text.lower()
    reasons, flags = [], []
    fit = 0.0

    # --- title fit
    if _any(p.title_exclude, title):
        job.bucket, job.score = "filtered", -100
        job.reasons = ["title excluded"]
        return job
    if _any(p.title_primary, title):
        fit += 35
        reasons.append("+35 core target title")
    elif _any(p.title_secondary, title):
        fit += 20
        reasons.append("+20 adjacent title")
    else:
        job.bucket, job.score = "filtered", -100
        job.reasons = ["title not a target"]
        return job
    if _any(p.title_entry_bonus, title):
        fit += 12
        reasons.append("+12 entry-level title")
    level_penalized = bool(_any(p.title_level_penalty, title))
    if level_penalized:
        fit -= 15
        reasons.append("-15 title implies mid-level (II)")

    # --- skills/keyword overlap with resume
    hits = _any(p.skills, low)
    domain = _any(p.domain_keywords, low)
    if job.description:
        skill_pts = min(30, len(hits) * 3)
        fit += skill_pts + min(10, len(domain) * 2.5)
        if hits:
            reasons.append(f"+{skill_pts} resume skills matched: {', '.join(_pretty(h) for h in hits[:8])}")
        if domain:
            reasons.append(f"+{min(10, len(domain) * 2.5):.0f} domain match: {', '.join(_pretty(d) for d in domain[:5])}")
    else:
        fit += 8
        reasons.append("+8 (no description available to match skills)")
    if job.segment in p.segment_bonus:
        fit += p.segment_bonus[job.segment]

    # --- experience required
    yrs, snip = years_required(job.description)
    job.years_required = yrs
    entry_text = _any(p.entry_phrases, low)
    if entry_text:
        fit += 12
        reasons.append("+12 posting explicitly welcomes new grads / entry level")
    if yrs is not None:
        if yrs <= p.max_years_ok:
            fit += 10
            reasons.append(f"+10 needs ~{yrs} yrs (within reach): \"{snip[:90]}\"")
            if level_penalized:
                fit += 15
                reasons.append("+15 ...but the posting's own requirements fit an MS with little experience")
        elif yrs <= p.max_years_ok + 1:
            fit -= 8
            reasons.append(f"-8 asks ~{yrs} yrs (a stretch; apply if strong match)")
        else:
            fit -= 25 + 4 * (yrs - p.max_years_ok - 2)
            reasons.append(f"-{25 + 4 * (yrs - p.max_years_ok - 2)} asks {yrs}+ yrs - likely ATS knockout")
            flags.append(f"{yrs}+ yrs required")
    if _PHD.search(job.title) or re.search(r"ph\.?d\.?\s+(is\s+)?required|requires? a ph\.?d", low):
        fit -= 25
        reasons.append("-25 PhD required")

    # --- location
    us = is_us(job)
    if us is False:
        job.bucket, job.score = "filtered", -100
        job.reasons = ["outside the US"]
        return job
    states = location_states(job.location)
    if states & set(p.preferred_states):
        fit += p.preferred_bonus
        reasons.append(f"+{p.preferred_bonus} preferred location ({', '.join(sorted(states & set(p.preferred_states)))})")
    if job.remote == "remote" or re.search(r"\bremote\b", job.location, re.I):
        flags.append("remote")

    # --- knockouts the candidate can't pass
    for pat, label in p.knockouts:
        if _rx(pat).search(low):
            fit -= 40
            flags.append(label)
            reasons.append(f"-40 knockout: {label}")

    # --- freshness: the biggest single lever against auto-rejection
    age = days_old(job, now)
    fresh = 0.0
    if age is None:
        reasons.append("posting date unknown")
    elif age <= 1:
        fresh = 25; reasons.append("+25 posted in the last 24h - apply today")
    elif age <= 3:
        fresh = 18; reasons.append(f"+18 posted {age:.0f} days ago")
    elif age <= 7:
        fresh = 10; reasons.append(f"+10 posted {age:.0f} days ago")
    elif age <= 14:
        fresh = 3
    elif age <= 30:
        fresh = -5; reasons.append(f"-5 posted {age:.0f} days ago")
    else:
        fresh = -15; reasons.append(f"-15 posted {age:.0f} days ago - applicant pile is deep")

    # --- ghost-job risk
    ghost = 0.0
    g_reasons = []
    ev = _any(p.evergreen_phrases, low)
    if ev:
        ghost += 35; g_reasons.append("evergreen/pipeline language")
    if age is not None and age > 60:
        ghost += 20; g_reasons.append(f"open {age:.0f} days")
    elif age is not None and age > 35:
        ghost += 10; g_reasons.append(f"open {age:.0f} days")
    if job.repost_count:
        ghost += min(40, 15 * job.repost_count); g_reasons.append(f"reposted {job.repost_count}x")
    if job.posted_at and job.first_seen and job.updated_at and (job.updated_at - job.posted_at).days > 45:
        ghost += 5; g_reasons.append("repeatedly edited/refreshed")
    if job.description and len(job.description) < 700:
        ghost += 10; g_reasons.append("very thin description")
    # signals that a real, time-boxed vacancy exists
    if job.extra.get("end_date") or re.search(
            r"(apply by|application (deadline|window)|posting (closes|will close|expected to close)|"
            r"anticipate the application window)", low):
        ghost -= 10; g_reasons.append("has an application deadline (good sign)")
    if re.search(r"\b(backfill|immediate (need|opening|start)|current vacancy|intends? to fill)\b", low):
        ghost -= 5; g_reasons.append("states a current vacancy (good sign)")
    if re.search(r"\b(\d{2,}) locations\b|multiple locations", job.location, re.I) or job.location.count(" / ") >= 5:
        ghost += 10; g_reasons.append("posted to many locations at once")

    # --- pay
    lo, hi, pay_snip = parse_salary(f"{job.salary}\n{job.description}")
    if lo:
        job.extra["salary_lo"], job.extra["salary_hi"] = lo, hi
        job.salary = job.salary or pay_snip
        top = hi or lo
        if top < p.min_salary:
            fit -= 20
            flags.append(f"low pay (max ~${top/1000:.0f}k/yr)")
            reasons.append(f"-20 pay tops out ~${top/1000:.0f}k/yr, under your ${p.min_salary/1000:.0f}k floor")
        else:
            fit += 5
            reasons.append(f"+5 pay posted: {pay_snip[:40]}")
    elif states & PAY_TRANSPARENCY and job.description:
        ghost += 5; g_reasons.append("no pay range despite pay-transparency law")
    contract = _any(p.contract_title, f"{job.employment_type}\n{job.title}".lower()) or _any(p.contract_phrases, low)
    if contract:
        flags.append("contract/temp")
        fit -= p.contract_penalty
        if p.contract_penalty:
            reasons.append(f"-{p.contract_penalty} contract/temp role")

    job.fit = round(fit, 1)
    ghost = max(0.0, ghost)
    job.ghost_risk = round(ghost, 1)
    if g_reasons:
        reasons.append(f"-{ghost:.0f} ghost-risk: {', '.join(g_reasons)}")
    job.score = round(fit + fresh - ghost, 1)
    job.reasons, job.flags = reasons, flags

    if job.ghost_risk >= 40:
        job.bucket = "likely ghost"
    elif job.score >= p.apply_now_score and (age is None or age <= 7):
        job.bucket = "apply now"
    elif job.score >= p.worth_it_score:
        job.bucket = "worth a shot"
    else:
        job.bucket = "long shot"
    return job


def _pretty(pattern: str) -> str:
    s = re.sub(r"\\b|\\s\*|\\s\+|\\|\(\?:|\)|\?|\^|\$", " ", pattern)
    s = s.split("|")[0]
    return " ".join(s.replace("\\", "").split())
