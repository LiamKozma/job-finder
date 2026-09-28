"""Turn the automatic daily search on/off from the app (Windows Task Scheduler / macOS launchd)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import BUNDLE_DIR, DATA_DIR, FROZEN

TASK = "JobFinderDaily"
LABEL = "com.jobfinder.daily"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no black console flash


def _launch_command() -> list[str]:
    """How the scheduler should start a headless search."""
    if FROZEN:
        return [sys.executable, "--auto"]
    exe = Path(sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")      # no console window
    return [str(exe), str(BUNDLE_DIR / "JobFinder.pyw"), "--auto"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)


def supported() -> bool:
    return os.name == "nt" or sys.platform == "darwin"


def is_enabled() -> bool:
    if os.name == "nt":
        return _run(["schtasks", "/Query", "/TN", TASK]).returncode == 0
    if sys.platform == "darwin":
        return (Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist").exists()
    return False


def enable(time_hhmm: str = "08:00") -> None:
    hh, mm = (int(x) for x in time_hhmm.split(":"))
    cmd = _launch_command()
    if os.name == "nt":
        from xml.sax.saxutils import escape
        args = " ".join(f'"{a}"' if " " in a else a for a in cmd[1:])
        # XML definition so we can set "run as soon as possible if a start was missed"
        # (laptop asleep at 8am) and "run on battery".
        xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Job Finder: daily search for fresh, real jobs</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>2026-01-01T{hh:02d}:{mm:02d}:00</StartBoundary><Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(cmd[0])}</Command><Arguments>{escape(args)}</Arguments></Exec></Actions>
</Task>"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as fh:
            fh.write(xml)
        try:
            r = _run(["schtasks", "/Create", "/F", "/TN", TASK, "/XML", fh.name])
        finally:
            os.unlink(fh.name)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip())
    elif sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        items = "".join(f"<string>{a}</string>" for a in cmd)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{items}</array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
  <key>StandardOutPath</key><string>{DATA_DIR / 'last-run.log'}</string>
  <key>StandardErrorPath</key><string>{DATA_DIR / 'last-run.log'}</string>
</dict></plist>""")
        _run(["launchctl", "unload", str(plist)])
        _run(["launchctl", "load", str(plist)])
    else:
        raise RuntimeError("Automatic scheduling is only set up for Windows and macOS.")


def disable() -> None:
    if os.name == "nt":
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"])
    elif sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
        _run(["launchctl", "unload", str(plist)])
        plist.unlink(missing_ok=True)
