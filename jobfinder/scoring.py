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
from .staleness import CompanyContext

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
# (VA/ME omitted: not confirmed as of Sep 2026)
PAY_TRANSPARENCY = {"CA", "CO", "WA", "NY", "IL", "MN", "MD", "HI", "MA", "VT", "NJ", "DC"}


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
    # "City, Region, CC" (Eightfold/Phenom style): trust the trailing ISO country code
    codes = {m.group(1) for part in loc.split(" / ")
             for m in [re.search(r",\s*[^,]+,\s*([A-Z]{2})\s*$", part.strip())] if m}
    if codes:
        return "US" in codes
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


# ---------------------------------------------------------------- dates in text
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_TXT = r"([a-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [a-z]{3,9}\.? \d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})"
_DEADLINE = re.compile(r"(application window[^.]{0,60}close[sd]? on|apply by|application deadline|applications? (will be )?"
                       r"accepted (until|through)|posting (will )?close[sd]? on|closing date|posting end date)\W{0,6}" + _DATE_TXT)


def parse_date_text(s: str) -> datetime | None:
    s = (s or "").strip().lower().replace(",", "").replace(".", "")
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
            return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
        if m:
            y = int(m.group(3)); y += 2000 if y < 100 else 0
            return datetime(y, int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
        m = re.fullmatch(r"([a-z]+) (\d{1,2}) (\d{4})", s) or re.fullmatch(r"(\d{1,2}) ([a-z]+) (\d{4})", s)
        if m:
            a, b, y = m.groups()
            mon, day = (a, b) if a.isalpha() else (b, a)
            return datetime(int(y), _MONTHS[mon[:3]], int(day), tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None
    return None


def deadline_in_text(low: str) -> datetime | None:
    m = _DEADLINE.search(low)
    return parse_date_text(m.group(m.lastindex)) if m else None


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


def score_job(job: Job, p: Profile, now: datetime | None = None, ctx: "CompanyContext | None" = None) -> Job:
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
    if any(k.lower() == "posting type" and str(v).lower().startswith("internal only")
           for k, v in (job.extra.get("custom") or {}).items()):
        job.bucket, job.score = "filtered", -100
        job.reasons = ["internal-only posting (not open to outside applicants)"]
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

    # --- age. A posting's date can be reset by a repost; the requisition's age can't.
    post_age = days_old(job, now)
    req_age, req_src = post_age, ""
    for cand, src in ((job.extra.get("req_age_history"), "first seen in your history"),
                      (job.extra.get("req_age_created"), "ATS creation date"),
                      (job.extra.get("req_age_estimate"), "estimated from its requisition number")):
        if cand is not None and (req_age is None or cand > req_age):
            req_age, req_src = cand, src
    job.extra["req_age"] = req_age
    refreshed = (post_age is not None and req_age is not None and req_age >= 60 and req_age - post_age >= 30)

    # --- freshness: the biggest single lever against auto-rejection
    fresh = 0.0
    if post_age is None:
        reasons.append("posting date unknown")
    elif post_age <= 1:
        fresh = 25; reasons.append("+25 posted in the last 24h - apply today")
    elif post_age <= 3:
        fresh = 18; reasons.append(f"+18 posted {post_age:.0f} days ago")
    elif post_age <= 7:
        fresh = 10; reasons.append(f"+10 posted {post_age:.0f} days ago")
    elif post_age <= 14:
        fresh = 3
    elif post_age <= 30:
        fresh = -5; reasons.append(f"-5 posted {post_age:.0f} days ago")
    else:
        fresh = -15; reasons.append(f"-15 posted {post_age:.0f} days ago - applicant pile is deep")
    if refreshed and fresh > 5:
        reasons.append(f"...but capped at +5: the requisition is ~{req_age:.0f} days old ({req_src}); "
                       f"the date was refreshed by a repost")
        fresh = 5
        flags.append(f"reposted old req (~{req_age:.0f}d)")

    # --- ghost-job risk. Weights follow evidence strength (see docs/GHOST_JOBS.md).
    ghost = 0.0
    g_reasons: list[str] = []

    def add(points: float, why: str) -> None:
        nonlocal ghost
        ghost += points
        g_reasons.append(f"{points:+g} {why}")

    stripped = ctx.strip_boilerplate(job.description).lower() if ctx else low
    cohort = re.search(r"cohort|rotational|development program|new grad|graduate program|early career program", low)
    # hard markers: the posting says (or the ATS records) that there is no single open seat
    if _any(p.pipeline_title, title) and not _any(p.pipeline_title_ok, title):
        add(45, "title marks a pipeline / talent-community posting")
    if job.extra.get("gh_prospect"):
        add(40, "Greenhouse 'prospect post' - not attached to any requisition")
    if job.source == "lever" and re.search(
            r"general (inquiry|opportunit|application)|talent (community|pool)|^pipeline$|future (opportunit|consideration)",
            job.department.lower()):
        add(35, "Lever general-application team")
    if _any(p.evergreen_phrases, stripped):
        add(10 if cohort else 35, "job-specific evergreen/pipeline language" + (" (cohort program)" if cohort else ""))
    if re.search(r"this posting is not for a current vacancy", low):
        add(60, "states it is NOT for a current vacancy (NY ghost-job law wording)")
    m = re.search(r"current vacancy,? and the employer intends to fill this position (by|no sooner than)\s+"
                  r"([a-z]+\.? \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4})", low)
    if m and m.group(1) == "by":
        d = parse_date_text(m.group(2))
        if d and d.date() < now.date():
            add(15, "fill-by date has passed but posting is still up")
        elif d:
            add(-15, "states a current vacancy with a fill-by date")
    if re.search(r"(is )?not (for )?(an? )?(existing|current) vacancy", low) and \
            not re.search(r"(existing|current) vacancy[^.]{0,80}new (position|role|headcount)", low):
        add(25, "states it is not an existing vacancy")
    elif re.search(r"\b(is|for) an existing vacancy|new position|new headcount|newly created (role|position)", low):
        add(-5, "states an existing vacancy / new headcount")
    if re.search(r"labor certification|application for permanent (labor|employment) certification|perm (recruitment|advertisement)", low):
        add(40, "PERM labor-certification ad (role is earmarked for a sponsored worker)")
        flags.append("PERM ad")
    cf = {k.lower(): str(v) for k, v in (job.extra.get("custom") or {}).items()}
    for k, v in cf.items():
        if re.search(r"req type|project type|recruiting type", k) and re.search(r"sourcing|pipeline|evergreen|talent pool", v, re.I):
            add(10 if re.search(r"intern|co-?op|new grad|graduate|apprentic", title) else 30,
                f"ATS requisition type is '{v}'")
        if (re.search(r"\btbh\b|to be hired|position (id|number)", k) and v.strip()) or \
                (k == "business justification" and re.search(r"replacement|new budgeted", v, re.I)):
            add(-8, "ATS shows a funded headcount / replacement")
            break
    ph = job.extra.get("phenom") or {}
    if str(ph.get("isEverGreenReq", "")).lower() in ("yes", "1", "true") or ph.get("jobRequisitionType") == "Evergreen" \
            or str(ph.get("justification", "")).lower().startswith("evergreen"):
        add(30, "ATS marks this as an evergreen requisition")
    elif re.search(r"replacement|additional hire \(budgeted\)|new position", f"{ph.get('newPosition', '')} {ph.get('justification', '')}", re.I):
        add(-6, "ATS shows a budgeted/replacement headcount")
    try:
        if int(ph.get("numberOpenings") or ph.get("noOfAvailableOpenings") or 0) - int(ph.get("openingsFilled") or 0) <= 0 \
                and ph.get("openingsFilled") not in (None, ""):
            add(30, "all openings already filled")
    except (TypeError, ValueError):
        pass

    # staleness of the requisition
    if req_age is not None:
        for limit, pts in ((180, 22), (120, 15), (90, 10), (60, 6)):
            if req_age > limit:
                add(pts, f"requisition open ~{req_age:.0f} days" + (f" ({req_src})" if req_src else ""))
                break
    if job.extra.get("relists"):
        n = job.extra["relists"]
        add(15 if n >= 2 else 10, f"re-listed {n}x after disappearing (seen in your history)")
    sfx = job.extra.get("wd_suffix", 0) - (ctx.wd_suffix_baseline if ctx else 0)
    if job.source == "workday" and sfx > 0:
        add(min(12, 6 * sfx), f"Workday re-posting #{job.extra.get('wd_suffix')} (this employer's norm is {ctx.wd_suffix_baseline if ctx else 0})")

    # deadlines stated in text (Workday's endDate is just an auto-expiry, so it's not used)
    dl = deadline_in_text(low) or parse_date_text(str(job.extra.get("end_date") or "")) if job.source != "workday" \
        else deadline_in_text(low)
    if dl:
        if dl.date() < now.date():
            add(15, f"application deadline {dl:%b %d} has passed")
        elif (dl - now).days <= 45:
            add(-4, f"application window closes {dl:%b %d}")

    # weaker, context-dependent signals
    if job.description and len(job.description) < 700:
        add(5, "very thin description")
    many = re.search(r"\b(\d{2,}) locations\b", job.location, re.I) or job.location.count(" / ") >= 9
    if many and not re.search(r"field|sales|territory|zone|region", title):
        add(3, "same posting in 10+ locations")
    if job.extra.get("restructuring_days") is not None:
        d = job.extra["restructuring_days"]
        add(5 if d <= 180 else 2, f"employer filed an SEC restructuring notice (8-K 2.05) {d} days ago")
    if job.extra.get("freeze"):
        add(5, "employer's open postings dropped 40%+ vs its 4-week norm (possible hiring freeze)")

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
    elif len(states) == 1 and states & PAY_TRANSPARENCY and job.description:
        add(5, "no pay range despite pay-transparency law")
    contract = _any(p.contract_title, f"{job.employment_type}\n{job.title}".lower()) or _any(p.contract_phrases, low)
    if contract:
        flags.append("contract/temp")
        fit -= p.contract_penalty
        if p.contract_penalty:
            reasons.append(f"-{p.contract_penalty} contract/temp role")

    job.fit = round(fit, 1)
    ghost = min(100.0, max(0.0, ghost))
    job.ghost_risk = round(ghost, 1)
    if g_reasons:
        reasons.append(f"ghost-risk {ghost:.0f}: " + "; ".join(g_reasons))
    job.score = round(fit + fresh - ghost, 1)
    job.reasons, job.flags = reasons, flags

    if job.ghost_risk >= 40:
        job.bucket = "likely ghost"
    elif job.score >= p.apply_now_score and (post_age is None or post_age <= 7) and not refreshed:
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
