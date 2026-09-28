from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .models import Company

# Where the shipped defaults live (inside the .exe bundle, or the repo checkout)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DEFAULT_CONFIG_DIR = BUNDLE_DIR / "config"
FROZEN = bool(getattr(sys, "frozen", False))
# Where the user's settings/history/reports live. The .exe can't write next to itself
# reliably, so it uses %LOCALAPPDATA%\JobFinder; a repo checkout uses the repo folder.
if os.environ.get("JOBFINDER_HOME"):
    ROOT = Path(os.environ["JOBFINDER_HOME"])
elif FROZEN:
    ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "JobFinder"
else:
    ROOT = BUNDLE_DIR
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# Plain-language settings the app window edits; they override profile.toml.
DEFAULT_SETTINGS = {
    "name": "",
    "min_salary": None,          # None = use profile.toml
    "preferred_states": None,
    "contract_ok": False,
    "needs_sponsorship": False,
    "has_clearance": False,
    "sec_contact_email": "",
    "daily_time": "08:00",
}
SPONSORSHIP_KNOCKOUT = (
    r"(unable|not able|not eligible|will not|won.?t|do(es)? not|cannot) (to )?(provide |offer )?(visa )?sponsor"
    r"|without (the need for )?(current or future )?(employer |visa )?sponsorship"
    r"|must be (a )?u\.?s\.? citizen|u\.?s\.? citizenship (is )?required",
    "no visa sponsorship")


def load_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    try:
        out.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return out


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


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


def load_profile(path: Path | None = None, settings: dict | None = None) -> Profile:
    if path is None:
        path = CONFIG_DIR / "profile.toml"
        if not path.exists():
            path = DEFAULT_CONFIG_DIR / "profile.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    t, s, sc, f = raw.get("titles", {}), raw.get("signals", {}), raw.get("scoring", {}), raw.get("filters", {})
    prof = Profile(
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
    return apply_settings(prof, load_settings() if settings is None else settings)


def apply_settings(p: Profile, st: dict) -> Profile:
    if st.get("name"):
        p.name = st["name"]
    if st.get("min_salary"):
        p.min_salary = int(st["min_salary"])
    if st.get("preferred_states") is not None:
        p.preferred_states = [x.strip().upper() for x in st["preferred_states"] if x.strip()]
    if st.get("contract_ok"):
        p.contract_penalty = 0
    if st.get("needs_sponsorship"):
        p.knockouts = p.knockouts + [SPONSORSHIP_KNOCKOUT]
    if st.get("has_clearance"):
        p.knockouts = [k for k in p.knockouts if "clearance" not in k[1]]
    if st.get("sec_contact_email"):
        p.sec_contact = st["sec_contact_email"]
    return p


COMPANY_FIELDS = ["name", "ats", "slug", "host", "site", "segment", "hq", "ticker"]


MY_COMPANIES = CONFIG_DIR / "my_companies.csv"   # employers the user added (kept across app updates)


def _read_companies(path: Path) -> list[Company]:
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("name") or row["name"].startswith("#"):
                continue
            out.append(Company(**{k: (row.get(k) or "").strip() for k in COMPANY_FIELDS}))
    return out


def load_companies(path: Path | None = None) -> list[Company]:
    if path is not None:
        return _read_companies(path)
    base = CONFIG_DIR / "companies.csv"
    if FROZEN or not base.exists():
        base = DEFAULT_CONFIG_DIR / "companies.csv"   # the app always uses its latest built-in list
    out = _read_companies(base)
    if MY_COMPANIES.exists():
        keys = {c.key for c in out}
        out += [c for c in _read_companies(MY_COMPANIES) if c.key not in keys]
    return out


def add_company(c: Company) -> None:
    """Persist a user-added employer (repo checkout: companies.csv; app: my_companies.csv)."""
    if FROZEN:
        existing = _read_companies(MY_COMPANIES) if MY_COMPANIES.exists() else []
        save_companies(existing + [c], MY_COMPANIES)
    else:
        save_companies(load_companies() + [c])


def save_companies(companies: list[Company], path: Path | None = None) -> None:
    path = path or CONFIG_DIR / "companies.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COMPANY_FIELDS)
        w.writeheader()
        for c in sorted(companies, key=lambda c: (c.segment, c.name.lower())):
            w.writerow({k: getattr(c, k) for k in COMPANY_FIELDS})
