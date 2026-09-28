"""SEC 8-K Item 2.05 ("Costs Associated with Exit or Disposal Activities") lookups.

A public company announcing a restructuring is a weak hiring-freeze signal, so it
only adds a few ghost-risk points. Results are cached in SQLite for a week.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from .http import request_json

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def restructuring_days(tickers: set[str], contact: str, db) -> dict[str, int]:
    """ticker -> days since the latest 8-K with Item 2.05 (only if within 365 days)."""
    if not contact or not tickers:
        return {}
    db.execute("CREATE TABLE IF NOT EXISTS sec_cache (key TEXT PRIMARY KEY, data TEXT, at TEXT)")
    headers = {"User-Agent": f"jobfinder personal job search {contact}"}
    now = datetime.now(timezone.utc)

    def cached(key: str, url: str, max_days: int = 7, keep=lambda d: d):
        row = db.execute("SELECT data, at FROM sec_cache WHERE key=?", (key,)).fetchone()
        if row and (now - datetime.fromisoformat(row[1])).days < max_days:
            return json.loads(row[0])
        time.sleep(0.15)                              # SEC asks for <10 requests/second
        data = keep(request_json(url, headers=headers))
        db.execute("INSERT OR REPLACE INTO sec_cache VALUES(?,?,?)", (key, json.dumps(data), now.isoformat()))
        db.commit()
        return data

    out: dict[str, int] = {}
    try:
        ciks = cached("tickers:" + ",".join(sorted(tickers)), TICKERS_URL, 30,
                      keep=lambda d: {v["ticker"]: v["cik_str"] for v in d.values() if v["ticker"] in tickers})
    except Exception:
        return out
    for tk in sorted(tickers):
        cik = ciks.get(tk)
        if not cik:
            continue
        def only_205(d):
            r = d["filings"]["recent"]
            return [r["filingDate"][i] for i in range(len(r["form"]))
                    if r["form"][i].startswith("8-K") and "2.05" in (r["items"][i] or "")]
        try:
            dates = cached(f"cik{cik}", f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", keep=only_205)
        except Exception:
            continue
        if dates:
            days = (now - datetime.fromisoformat(max(dates)).replace(tzinfo=timezone.utc)).days
            if days <= 365:
                out[tk] = days
    return out
