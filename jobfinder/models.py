from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Company:
    """One employer feed. Meaning of slug/host/site depends on the ATS:

    greenhouse/lever/ashby/smartrecruiters/workable/recruitee: slug = board name
    workday:   host = acme.wd5.myworkdayjobs.com, slug = tenant, site = career site
    oracle:    host = xxxx.fa.us2.oraclecloud.com, site = CX_1
    phenom:    host = careers.acme.com, site = "en_us/us" (lang/country)
    eightfold: host = acme.eightfold.ai, slug = acme.com
    """
    name: str
    ats: str
    slug: str = ""
    host: str = ""
    site: str = ""
    segment: str = ""
    hq: str = ""

    @property
    def key(self) -> str:
        return ":".join(x for x in (self.ats, self.host, self.slug, self.site) if x).lower()


@dataclass
class Job:
    company: str
    source: str               # ats name
    ext_id: str               # id inside the ATS
    title: str
    location: str
    url: str
    description: str = ""     # plain text
    posted_at: datetime | None = None
    updated_at: datetime | None = None
    req_id: str = ""
    remote: str = ""          # "remote" | "hybrid" | "onsite" | ""
    salary: str = ""
    department: str = ""
    employment_type: str = ""
    segment: str = ""
    extra: dict = field(default_factory=dict)

    # filled in by scoring
    score: float = 0.0
    fit: float = 0.0
    ghost_risk: float = 0.0
    bucket: str = ""
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    years_required: int | None = None

    # filled in by the store
    first_seen: datetime | None = None
    repost_count: int = 0
    is_new: bool = False

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.company}:{self.ext_id}"

    @property
    def fingerprint(self) -> str:
        """Identity that survives a repost: same company, same normalized title, same city."""
        t = re.sub(r"[^a-z0-9 ]", " ", self.title.lower())
        t = re.sub(r"\b(i{1,3}|1|2|3|iv)\b", " ", t)  # Engineer I/II is often reposted as the other
        t = " ".join(t.split())
        loc = re.sub(r"[^a-z]", "", self.location.lower().split(",")[0])
        return f"{self.company.lower()}|{t}|{loc}"
