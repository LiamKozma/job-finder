"""SQLite memory across daily runs.

This is what lets the tool spot reposts (same role, new id) and tell you what's
new since yesterday, and it remembers what you applied to or hid.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    company TEXT, title TEXT, location TEXT, url TEXT,
    posted_at TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    score REAL, bucket TEXT
);
CREATE INDEX IF NOT EXISTS jobs_fp ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS marks (
    uid TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS details (uid TEXT PRIMARY KEY, data TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reqs (
    req_key TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_uid TEXT, relists INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS company_counts (day TEXT, company TEXT, total INTEGER, ok INTEGER, PRIMARY KEY(day, company));
CREATE TABLE IF NOT EXISTS runs (at TEXT PRIMARY KEY, companies INTEGER, jobs INTEGER, errors TEXT);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def last_run(self) -> datetime | None:
        row = self.db.execute("SELECT max(at) FROM runs").fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def annotate(self, jobs: list[Job], now: datetime) -> None:
        """Before scoring: first_seen / is_new, requisition age from history, and relists."""
        for j in jobs:
            row = self.db.execute("SELECT first_seen FROM jobs WHERE uid=?", (j.uid,)).fetchone()
            if row:
                j.first_seen = datetime.fromisoformat(row[0])
            else:
                j.first_seen, j.is_new = now, True
            relists = 0
            # the same requisition under a new posting id, after it had disappeared for 7+ days
            r = self.db.execute("SELECT first_seen, last_seen, last_uid, relists FROM reqs WHERE req_key=?",
                                (req_key(j),)).fetchone()
            if r:
                first, last, last_uid, relists = datetime.fromisoformat(r[0]), datetime.fromisoformat(r[1]), r[2], r[3]
                if last_uid != j.uid and (now - last).days >= 7:
                    relists += 1
                j.extra["req_age_history"] = (now - min(first, j.posted_at or first)).total_seconds() / 86400
            # same role + city that vanished before this one appeared (a repost under a new id)
            gone = self.db.execute(
                "SELECT count(*) FROM jobs WHERE fingerprint=? AND uid<>? AND last_seen < ?",
                (j.fingerprint, j.uid, (j.first_seen or now).isoformat())).fetchone()[0]
            j.repost_count = max(relists, gone)
            if j.repost_count:
                j.extra["relists"] = j.repost_count

    def record_reqs(self, jobs: list[Job], now: datetime) -> None:
        ts = now.isoformat()
        for j in jobs:
            k = req_key(j)
            r = self.db.execute("SELECT last_seen, last_uid, relists FROM reqs WHERE req_key=?", (k,)).fetchone()
            if r is None:
                first = min(now, j.posted_at) if j.posted_at else now
                self.db.execute("INSERT INTO reqs VALUES(?,?,?,?,0)", (k, first.isoformat(), ts, j.uid))
            else:
                relisted = r[1] != j.uid and (now - datetime.fromisoformat(r[0])).days >= 7
                self.db.execute("UPDATE reqs SET last_seen=?, last_uid=?, relists=relists+? WHERE req_key=?",
                                (ts, j.uid, int(relisted), k))

    def record_counts(self, totals: dict[str, int], errors: dict[str, str], now: datetime) -> None:
        day = now.astimezone().strftime("%Y-%m-%d")
        self.db.executemany("INSERT OR REPLACE INTO company_counts VALUES(?,?,?,?)",
                            [(day, c, n, int(c not in errors)) for c, n in totals.items()])
        self.db.commit()

    def freezes(self) -> set[str]:
        """Companies whose open-posting count sat at <=60% of their 28-day median for 3 straight good runs."""
        out = set()
        rows = self.db.execute("SELECT company, day, total FROM company_counts WHERE ok=1 AND day >= date('now','-35 days')"
                               " ORDER BY company, day").fetchall()
        by: dict[str, list[int]] = {}
        for c, _, n in rows:
            by.setdefault(c, []).append(n)
        for c, ns in by.items():
            if len(ns) < 28:
                continue          # needs four weeks of clean history
            base = sorted(ns[:-3])[len(ns[:-3]) // 2]
            if base >= 15 and all(n <= 0.6 * base for n in ns[-3:]):
                out.add(c)
        return out

    def save(self, jobs: list[Job], now: datetime, companies: int, errors: dict[str, str]) -> None:
        ts = now.isoformat()
        for j in jobs:
            self.db.execute(
                """INSERT INTO jobs(uid, fingerprint, company, title, location, url, posted_at, first_seen, last_seen, score, bucket)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen, score=excluded.score,
                     bucket=excluded.bucket, title=excluded.title, location=excluded.location, url=excluded.url""",
                (j.uid, j.fingerprint, j.company, j.title, j.location, j.url,
                 j.posted_at.isoformat() if j.posted_at else None,
                 (j.first_seen or now).isoformat(), ts, j.score, j.bucket))
        self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?)", (ts, companies, len(jobs), json.dumps(errors)))
        self.db.commit()

    def load_details(self, keep_days: int = 120) -> dict[str, dict]:
        self.db.execute("DELETE FROM details WHERE at < datetime('now', ?)", (f"-{keep_days} days",))
        return {uid: json.loads(data) for uid, data in self.db.execute("SELECT uid, data FROM details")}

    def save_details(self, fresh: dict[str, dict]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.db.executemany("INSERT OR REPLACE INTO details VALUES(?,?,?)",
                            [(uid, json.dumps(d), now) for uid, d in fresh.items()])
        self.db.commit()

    def marks(self) -> dict[str, str]:
        return dict(self.db.execute("SELECT uid, status FROM marks").fetchall())

    def mark(self, needle: str, status: str, note: str = "") -> list[tuple[str, str, str]]:
        """Mark jobs whose uid / url / short id matches `needle`. Returns matches."""
        rows = self.db.execute(
            "SELECT uid, company, title FROM jobs WHERE uid=? OR url=?", (needle, needle)).fetchall()
        if not rows:
            rows = [r for r in self.db.execute("SELECT uid, company, title FROM jobs").fetchall()
                    if short_id(r[0]) == needle.lower()]
        for uid, _, _ in rows:
            self.db.execute("INSERT OR REPLACE INTO marks VALUES(?,?,?,?)",
                            (uid, status, note, datetime.now(timezone.utc).isoformat()))
        self.db.commit()
        return rows

    def applied(self) -> list[tuple]:
        return self.db.execute(
            """SELECT m.at, j.company, j.title, j.location, j.url, m.note FROM marks m
               JOIN jobs j ON j.uid=m.uid WHERE m.status='applied' ORDER BY m.at DESC""").fetchall()


def req_key(j: Job) -> str:
    """Identity of the underlying requisition (survives re-posting under a new posting id)."""
    rid = j.extra.get("internal_job_id") or j.req_id
    return f"{j.company}|{rid}" if rid else f"fp|{j.fingerprint}"


def short_id(uid: str) -> str:
    """Stable 6-char id that is easy to type: `jobfinder applied 3fa9c1`."""
    import hashlib
    return hashlib.sha1(uid.encode()).hexdigest()[:6]
