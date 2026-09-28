"""Company-level context used by the ghost-job signals.

Some signals can only be judged against the rest of a company's postings:

* Requisition age. Workday and SmartRecruiters reset a posting's date when an
  old requisition is re-posted, so "Posted 3 days ago" can sit on a req that
  was opened five months ago. Requisition numbers are handed out roughly in
  order, so from the postings whose date *is* exact we estimate how many reqs
  per day a company opens, and from that how old any given req number is.
  Validated against ATS creation timestamps (Phenom/Eightfold): precision
  0.80-1.00 for "older than 60 days", median error 0-3 days.
* Boilerplate. Sentences that appear in most of a company's postings (EEO
  text, "our drug pipeline"...) are ignored by the phrase detectors.
* Workday "-1" suffixes are the default at many tenants (70%+ at Medtronic/BD),
  so only a suffix above the tenant's usual value means anything.
* Bulk creation stamps (a whole board migrated at 23:47 one night) are not
  creation dates.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from .models import Job

_REQ = re.compile(r"^([A-Za-z]{0,4}[-_]?)(\d{4,10})$")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def req_series(req_id: str) -> tuple[tuple[str, int], int] | None:
    """'R-070752' -> (('R-', 6), 70752). IDs of different shapes are different sequences."""
    m = _REQ.match(re.sub(r"\s+", "", str(req_id or "")))
    if not m:
        return None
    return (m.group(1).upper(), len(m.group(2))), int(m.group(2))


def sentences(text: str) -> list[str]:
    out = []
    for s in _SENT_SPLIT.split(text.lower()):
        s = " ".join(s.split())
        if len(s) > 25:
            out.append(s)
    return out


@dataclass
class Series:
    n_now: int          # newest req number currently posted
    rate: float         # reqs opened per day
    points: int


@dataclass
class CompanyContext:
    boilerplate: set[str] = field(default_factory=set)
    wd_suffix_baseline: int = 0
    series: dict[tuple[str, int], list[tuple[int, int, Series]]] = field(default_factory=dict)
    bulk_created: set[str] = field(default_factory=set)   # 'YYYY-MM-DDTHH' stamps shared by >=10 jobs

    def req_age_estimate(self, job: Job) -> float | None:
        """Estimated days since this posting's requisition was opened, or None."""
        parsed = req_series(job.req_id)
        if not parsed:
            return None
        key, n = parsed
        for lo, hi, s in self.series.get(key, []):
            # old reqs can sit below the dense block; accept up to a year's worth of numbers below it
            if lo - 365 * s.rate <= n <= hi:
                return max(0.0, min(730.0, (s.n_now - n) / s.rate))
        return None

    def created_at(self, job: Job) -> datetime | None:
        """ATS-provided creation time (Phenom dateCreated / Eightfold creationTs), unless it's a bulk stamp."""
        raw = job.extra.get("created") or ""
        if not raw or raw[:13] in self.bulk_created:
            return None
        from .sources import parse_dt
        return parse_dt(raw)

    def strip_boilerplate(self, text: str) -> str:
        if not self.boilerplate:
            return text
        return "\n".join(s for s in sentences(text) if s not in self.boilerplate)


def _theil_sen(points: list[tuple[float, float]]) -> float | None:
    slopes = [(y2 - y1) / (x2 - x1) for i, (x1, y1) in enumerate(points)
              for x2, y2 in points[i + 1:] if x2 != x1]
    return median(slopes) if slopes else None


def _clusters(nums: list[int]) -> list[tuple[int, int]]:
    """Split a sorted set of req numbers into runs; a jump >10% of the value starts a new stream
    (e.g. Abbott's 3100xxxx vs 3500xxxx). Smaller gaps are just old reqs within one stream."""
    runs, start, prev = [], None, None
    for n in sorted(set(nums)):
        if start is None:
            start = prev = n
        elif n - prev > 0.10 * n:
            runs.append((start, prev))
            start = n
        prev = n
    if start is not None:
        runs.append((start, prev))
    return runs


def fit_series(pairs: list[tuple[int, float]]) -> list[tuple[int, int, Series]]:
    """pairs = (req number, exact posting age in days, <= 29).

    Returns [(lo, hi, Series)] per contiguous req-number stream. For each posting
    age we take the *median* req number posted that day (robust to sparse or
    capped sampling, unlike the maximum), then fit req-number vs age with a
    Theil-Sen line. Series.n_now is the line's value at age 0, so an estimated
    age is "how many days ago a typical posting had this req number".
    """
    out = []
    for lo, hi in _clusters([n for n, _ in pairs]):
        pts = [(n, a) for n, a in pairs if lo <= n <= hi]
        if len(pts) < 30:
            continue
        by_age: dict[int, list[int]] = defaultdict(list)
        for n, a in pts:
            by_age[int(a)].append(n)
        meds = [(a, median(ns)) for a, ns in sorted(by_age.items()) if len(ns) >= 2]
        if len(meds) < 10 or meds[-1][0] - meds[0][0] < 14:
            continue                      # too few days observed to trust a slope
        slope = _theil_sen(meds)
        if slope is None or slope >= -0.5:
            continue
        intercept = median([m - slope * a for a, m in meds])
        s = Series(n_now=int(intercept), rate=-slope, points=len(pts))
        # self-check: on its own recent postings the fit should rarely claim a 60+ day gap
        # (7-18% measured across big employers); if it does, the stream is too irregular
        flagged = sum(1 for n, a in pts if (s.n_now - n) / s.rate - a >= 60)
        if flagged > 0.25 * len(pts):
            continue
        out.append((lo, hi, s))
    return out


def build_contexts(jobs: list[Job], now: datetime) -> dict[str, CompanyContext]:
    by_co: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        by_co[j.company].append(j)
    out = {}
    for co, js in by_co.items():
        ctx = CompanyContext()
        # boilerplate: sentences in >=50% of this company's descriptions
        descs = [j.description for j in js if len(j.description) > 200]
        if len(descs) >= 5:
            cnt = Counter(s for d in descs for s in set(sentences(d)))
            ctx.boilerplate = {s for s, k in cnt.items() if k >= 0.5 * len(descs)}
        # workday suffix baseline (mode)
        sfx = [j.extra.get("wd_suffix", 0) for j in js if j.source == "workday"]
        if sfx:
            ctx.wd_suffix_baseline = Counter(sfx).most_common(1)[0][0]
        # requisition-number sequences, fit only on exact, recent posting dates
        pairs: dict[tuple[str, int], list[tuple[int, float]]] = defaultdict(list)
        for j in js:
            if j.source not in ("workday", "smartrecruiters", "oracle") or not j.posted_at:
                continue
            if j.source == "workday" and not j.extra.get("age_exact", True):
                continue
            age = (now - j.posted_at).total_seconds() / 86400
            parsed = req_series(j.req_id)
            if parsed and 0 <= age <= 29:
                pairs[parsed[0]].append((parsed[1], age))
        for key, pr in pairs.items():
            fitted = fit_series(pr)
            if fitted:
                ctx.series[key] = fitted
        stamps = Counter((j.extra.get("created") or "")[:13] for j in js if j.extra.get("created"))
        ctx.bulk_created = {h for h, k in stamps.items() if k >= 10}
        out[co] = ctx
    return out
