"""The Job Finder app window (tkinter, ships with Python - no extra installs).

Also the entry point for the Windows .exe:
    JobFinder.exe              open the window
    JobFinder.exe --auto       headless daily search (used by the scheduler), opens the report
    JobFinder.exe --selftest   quick check on 3 employers (used by the build)
"""
from __future__ import annotations

import csv
import os
import queue
import sys
import threading
import traceback
import webbrowser
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import DATA_DIR, REPORTS_DIR, ROOT, load_settings, save_settings

HELP_URL = "https://github.com/LiamKozma/job-finder#readme"
STRATEGY_URL = "https://github.com/LiamKozma/job-finder/blob/main/STRATEGY.md"


def _log_to_file() -> None:
    """A windowed .exe has no console; send prints/errors to a log file instead."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        log = open(DATA_DIR / "last-run.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log


def run_search(progress=None, open_report: bool = True, company: str | None = None) -> int:
    from .cli import cmd_run
    args = Namespace(segment=None, company=company, workers=12, no_open=not open_report, new_first=True)
    return cmd_run(args, progress=progress)


def last_summary() -> str:
    path = REPORTS_DIR / "latest.csv"
    if not path.exists():
        return "No search yet. Click “Find jobs now” to run your first one (takes about 3 minutes)."
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
    n = {b: sum(r["bucket"] == b for r in rows) for b in ("apply now", "worth a shot")}
    new = sum(r["new"] == "yes" for r in rows)
    return (f"Last search: {when}\n{n['apply now']} to apply today · {n['worth a shot']} worth a shot"
            + (f" · {new} new since the search before" if new else ""))


def open_report() -> None:
    path = REPORTS_DIR / "latest.html"
    if path.exists():
        webbrowser.open(path.resolve().as_uri())


class App:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root = tk.Tk()
        root.title("Job Finder")
        root.minsize(520, 0)
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        st = load_settings()

        style = ttk.Style()
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=("Segoe UI", 13, "bold"), padding=(18, 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", foreground="#666")

        pad = {"padx": 16, "pady": 6}
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Job Finder", style="Title.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text="Finds fresh, real engineering jobs that fit you — and skips the ghost jobs.",
                  style="Muted.TLabel").pack(anchor="w", padx=16)

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=16, pady=(14, 4))
        self.find_btn = ttk.Button(row, text="Find jobs now", style="Big.TButton", command=self.start_search)
        self.find_btn.pack(side="left")
        ttk.Button(row, text="Open last results", command=open_report).pack(side="left", padx=10)

        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.bar.pack(fill="x", **pad)
        self.status = tk.StringVar(value=last_summary())
        ttk.Label(frm, textvariable=self.status, justify="left", wraplength=480).pack(anchor="w", padx=16)

        # ---- preferences
        pf = ttk.LabelFrame(frm, text=" Your preferences ", padding=10)
        pf.pack(fill="x", padx=16, pady=(16, 6))
        self.v_name = tk.StringVar(value=st.get("name") or "")
        self.v_salary = tk.StringVar(value=str(st.get("min_salary") or 65000))
        self.v_states = tk.StringVar(value=", ".join(st.get("preferred_states") or ["GA"]))
        self.v_contract = tk.BooleanVar(value=bool(st.get("contract_ok")))
        self.v_sponsor = tk.BooleanVar(value=bool(st.get("needs_sponsorship")))
        self.v_clear = tk.BooleanVar(value=bool(st.get("has_clearance")))
        grid = [("Your name (shown on the results page)", self.v_name),
                ("Lowest yearly salary you'd accept ($)", self.v_salary),
                ("States you'd prefer (optional, e.g. GA, NC)", self.v_states)]
        for i, (label, var) in enumerate(grid):
            ttk.Label(pf, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(pf, textvariable=var, width=22).grid(row=i, column=1, sticky="we", padx=(10, 0), pady=3)
        checks = [("Contract / temporary jobs are OK", self.v_contract),
                  ("I need visa sponsorship to work in the US", self.v_sponsor),
                  ("I have an active security clearance", self.v_clear)]
        for j, (label, var) in enumerate(checks, start=len(grid)):
            ttk.Checkbutton(pf, text=label, variable=var).grid(row=j, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(pf, text="Save preferences", command=self.save_prefs).grid(
            row=len(grid) + len(checks), column=0, sticky="w", pady=(8, 0))
        pf.columnconfigure(1, weight=1)

        # ---- automatic daily search
        from . import schedule
        self.schedule = schedule
        af = ttk.LabelFrame(frm, text=" Automatic daily search ", padding=10)
        af.pack(fill="x", padx=16, pady=6)
        self.v_auto = tk.BooleanVar(value=schedule.is_enabled() if schedule.supported() else False)
        self.v_time = tk.StringVar(value=st.get("daily_time") or "08:00")
        r2 = ttk.Frame(af)
        r2.pack(anchor="w")
        ttk.Checkbutton(r2, text="Search for me automatically every day at", variable=self.v_auto,
                        command=self.toggle_auto).pack(side="left")
        times = [f"{h:02d}:00" for h in range(6, 13)]
        cb = ttk.Combobox(r2, textvariable=self.v_time, values=times, width=6, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.toggle_auto() if self.v_auto.get() else None)
        ttk.Label(af, text="The results open in your browser when it's done. If the laptop is asleep,\n"
                           "it runs as soon as it wakes up.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        # ---- footer
        ft = ttk.Frame(frm)
        ft.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Button(ft, text="How to get interviews (tips)", command=lambda: webbrowser.open(STRATEGY_URL)).pack(side="left")
        ttk.Button(ft, text="Help", command=lambda: webbrowser.open(HELP_URL)).pack(side="left", padx=8)
        ttk.Label(ft, text=f"v{__version__}", style="Muted.TLabel").pack(side="right")

        root.after(150, self.poll)

    # ---------------------------------------------------------------- actions
    def save_prefs(self, quiet: bool = False) -> bool:
        from tkinter import messagebox
        try:
            salary = int(self.v_salary.get().replace(",", "").replace("$", "").strip() or 0)
        except ValueError:
            messagebox.showerror("Job Finder", "Salary should be a number, like 70000.")
            return False
        st = load_settings()
        st.update({
            "name": self.v_name.get().strip(),
            "min_salary": salary or None,
            "preferred_states": [s.strip().upper() for s in self.v_states.get().replace(";", ",").split(",") if s.strip()],
            "contract_ok": self.v_contract.get(),
            "needs_sponsorship": self.v_sponsor.get(),
            "has_clearance": self.v_clear.get(),
            "daily_time": self.v_time.get(),
        })
        save_settings(st)
        if not quiet:
            messagebox.showinfo("Job Finder", "Saved. Your next search will use these preferences.")
        return True

    def toggle_auto(self) -> None:
        from tkinter import messagebox
        self.save_prefs(quiet=True)
        try:
            if self.v_auto.get():
                self.schedule.enable(self.v_time.get())
                messagebox.showinfo("Job Finder", f"Done! Job Finder will search every day at {self.v_time.get()}.")
            else:
                self.schedule.disable()
        except Exception as e:
            self.v_auto.set(False)
            messagebox.showerror("Job Finder", f"Couldn't set up the daily search:\n{e}")

    def start_search(self) -> None:
        if self.busy:
            return
        if not self.save_prefs(quiet=True):
            return
        self.busy = True
        self.find_btn.state(["disabled"])
        self.bar["value"] = 0
        self.status.set("Starting… this takes about 3 minutes. You can keep using your computer.")

        def progress(done, total, postings, msg):
            self.q.put(("progress", done, total, postings, msg))

        def work():
            try:
                rc = run_search(progress=progress)
                self.q.put(("done", rc))
            except Exception:
                traceback.print_exc()
                self.q.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self) -> None:
        from tkinter import messagebox
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "progress":
                    _, done, total, postings, msg = item
                    self.bar["value"] = 100 * done / max(1, total)
                    self.status.set(f"Checked {done} of {total} employers · {postings:,} postings scanned\n{msg}")
                elif item[0] == "done":
                    self.busy = False
                    self.find_btn.state(["!disabled"])
                    self.bar["value"] = 100
                    self.status.set(last_summary() + "\nYour results opened in your web browser.")
                elif item[0] == "error":
                    self.busy = False
                    self.find_btn.state(["!disabled"])
                    self.status.set("Something went wrong. Check your internet connection and try again.")
                    messagebox.showerror("Job Finder", "The search failed. Details were saved to:\n"
                                         f"{DATA_DIR / 'last-run.log'}\n\n{item[1][-600:]}")
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def run(self) -> None:
        self.root.mainloop()


def selftest() -> int:
    """Small real search used to verify a build: 3 employers, no browser."""
    rc = run_search(open_report=False, company="Medtronic")
    ok = rc == 0 and (REPORTS_DIR / "latest.html").exists() and (REPORTS_DIR / "latest.csv").exists()
    print("SELFTEST", "OK" if ok else "FAILED", ROOT)
    import tkinter  # noqa: F401  - make sure the GUI toolkit is bundled
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _log_to_file()
    if "--selftest" in argv:
        return selftest()
    if "--auto" in argv:
        try:
            return run_search(open_report=True)
        except Exception:
            traceback.print_exc()
            return 1
    App().run()
    return 0
