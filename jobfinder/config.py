from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .models import Company

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"


@dataclass
class Profile:
    name: str = ""
    title_primary: list[str] = field(default_factory=list)
    title_secondary: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    title_entry_bonus: list[str] = field(default_factory=list)
    title_level_penalty: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domain_keywords: list[str] = field(default_factory=list)
    entry_phrases: list[str] = field(default_factory=list)
    evergreen_phrases: list[str] = field(default_factory=list)
    pipeline_title: list[str] = field(default_factory=list)
    pipeline_title_ok: list[str] = field(default_factory=list)
    contract_phrases: list[str] = field(default_factory=list)
    contract_title: list[str] = field(default_factory=list)
    knockouts: list[tuple[str, str]] = field(default_factory=list)
    workday_queries: list[str] = field(default_factory=lambda: ["engineer"])
    preferred_states: list[str] = field(default_factory=list)
    preferred_bonus: int = 5
    segment_bonus: dict[str, float] = field(default_factory=dict)
    max_years_ok: int = 2
    min_salary: int = 65000
    contract_penalty: int = 10
    apply_now_score: float = 70
    worth_it_score: float = 45
    max_age_days: int = 45
    sec_contact: str = ""


def load_profile(path: Path | None = None) -> Profile:
    path = path or CONFIG_DIR / "profile.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    t, s, sc, f = raw.get("titles", {}), raw.get("signals", {}), raw.get("scoring", {}), raw.get("filters", {})
    return Profile(
        name=raw.get("name", ""),
        title_primary=t.get("primary", []),
        title_secondary=t.get("secondary", []),
        title_exclude=t.get("exclude", []),
        title_entry_bonus=t.get("entry_bonus", []),
        title_level_penalty=t.get("level_penalty", []),
        skills=raw.get("skills", {}).get("patterns", []),
        domain_keywords=raw.get("skills", {}).get("domain", []),
        entry_phrases=s.get("entry_level", []),
        evergreen_phrases=s.get("evergreen", []),
        pipeline_title=s.get("pipeline_title", []),
        pipeline_title_ok=s.get("pipeline_title_ok", []),
        contract_phrases=s.get("contract", []),
        contract_title=s.get("contract_title", []),
        knockouts=[(k["pattern"], k["label"]) for k in s.get("knockouts", [])],
        workday_queries=f.get("workday_queries", ["engineer"]),
        preferred_states=f.get("preferred_states", []),
        preferred_bonus=sc.get("preferred_location_bonus", 5),
        segment_bonus=sc.get("segment_bonus", {}),
        max_years_ok=sc.get("max_years_ok", 2),
        min_salary=sc.get("min_salary", 65000),
        contract_penalty=sc.get("contract_penalty", 10),
        apply_now_score=sc.get("apply_now_score", 70),
        worth_it_score=sc.get("worth_it_score", 45),
        max_age_days=f.get("max_age_days", 45),
        sec_contact=raw.get("sec", {}).get("contact_email", ""),
    )


COMPANY_FIELDS = ["name", "ats", "slug", "host", "site", "segment", "hq", "ticker"]


def load_companies(path: Path | None = None) -> list[Company]:
    path = path or CONFIG_DIR / "companies.csv"
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("name") or row["name"].startswith("#"):
                continue
            out.append(Company(**{k: (row.get(k) or "").strip() for k in COMPANY_FIELDS}))
    return out


def save_companies(companies: list[Company], path: Path | None = None) -> None:
    path = path or CONFIG_DIR / "companies.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COMPANY_FIELDS)
        w.writeheader()
        for c in sorted(companies, key=lambda c: (c.segment, c.name.lower())):
            w.writerow({k: getattr(c, k) for k in COMPANY_FIELDS})
