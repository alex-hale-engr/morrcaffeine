#!/usr/bin/env python3
# Usage:
#   python3 morrcaffeine_macos.py --start-window-start 08:30 --start-window-end 10:00 --days-of-week Mon,Tue,Wed,Thu,Fri --min-duration-minutes 120 --max-duration-minutes 240 --interval-seconds 60
#
# What it does:
# - Starts a macOS no-lock mechanism immediately (caffeinate) and keeps it active for as long as this script runs.
# - Runs an immediate F13 session on launch (random duration in range).
# - Then schedules future F13 sessions:
#   - Random start time inside a daily time window
#   - Only on specified weekdays
#   - Random duration in range
# - During an F13 session, it sends F13 at a fixed interval using osascript/System Events.
# - Shows a live countdown progress line for sessions and waiting.
# - Interactive controls:
#   - Press E to end the current F13 session early (no-lock remains active)
#   - Press Q to quit the script (and stop no-lock)
#
# Notes:
# - No-lock is implemented via /usr/bin/caffeinate (IOKit power assertion). This does NOT generate keyboard/mouse input.
# - Sending F13 requires macOS permissions:
#   - System Settings -> Privacy & Security -> Accessibility: allow your terminal app (Terminal/iTerm2)
#   - System Settings -> Privacy & Security -> Automation: allow your terminal app to control "System Events" (prompted on first run)
# - Time windows do not cross midnight (end must be later than start on the same day).

import argparse
import datetime as dt
import os
import random
import select
import signal
import subprocess
import sys
import termios
import tty
import atexit

DAY_MAP = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}

DOW_ABBREV = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}

F13_KEYCODE = 105  # macOS "key code" for F13 in System Events


class RawTerminal:
    def __init__(self):
        self._fd = None
        self._old = None

    def __enter__(self):
        if not sys.stdin.isatty():
            return self
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fd is not None and self._old is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)


def normalize_days(days_csv: str):
    parts = [p.strip() for p in days_csv.split(",") if p.strip()]
    normalized = []
    for p in parts:
        key = p.strip().lower()
        if len(key) >= 3:
            key = key[:3]
        if key in DAY_MAP:
            normalized.append(DAY_MAP[key])
    if not normalized:
        raise ValueError("DaysOfWeek is empty or invalid. Use values like Mon,Tue,Wed,Thu,Fri,Sat,Sun.")
    return normalized


def parse_time_of_day(hhmm: str) -> dt.time:
    # Accepts H:MM, HH:MM, optionally seconds
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(hhmm, fmt).time()
        except ValueError:
            continue
    # Also allow single-digit hour like 8:30 via %H:%M already supports it, but keep this message explicit.
    raise ValueError("Invalid time format. Use HH:MM or HH:MM:SS.")


def day_abbrev(date_obj: dt.date) -> str:
    return DOW_ABBREV[date_obj.weekday()]


def dt_to_str(x: dt.datetime) -> str:
    return x.strftime("%Y-%m-%d %H:%M:%S")


def format_hhmmss(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    td = dt.timedelta(seconds=seconds)
    total = int(td.total_seconds())
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def print_progress_line(activity: str, status: str, percent: int | None):
    # Single-line, overwrite in-place
    if percent is None:
        bar = ""
    else:
        width = 24
        done = int((percent / 100) * width)
        if done < 0:
            done = 0
        if done > width:
            done = width
        bar = "[" + ("#" * done) + ("-" * (width - done)) + f"] {percent:3d}%  "

    line = f"{activity}: {status} {bar}"
    # Pad to clear previous content
    if len(line) < 120:
        line = line + (" " * (120 - len(line)))
    sys.stdout.write("\r" + line)
    sys.stdout.flush()


def clear_progress_line():
    sys.stdout.write("\r" + (" " * 140) + "\r")
    sys.stdout.flush()


def read_key_nonblocking():
    # Returns uppercase char if available; else None.
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], 0)
    if r:
        ch = os.read(sys.stdin.fileno(), 1)
        if not ch:
            return None
        try:
            return ch.decode("utf-8", errors="ignore").upper()
        except Exception:
            return None
    return None


def start_caffeinate():
    caffeinate_path = "/usr/bin/caffeinate"
    if not os.path.exists(caffeinate_path):
        raise RuntimeError("ERROR: /usr/bin/caffeinate not found. This script requires macOS.")
    # -d: prevent display sleep
    # -i: prevent idle system sleep
    # -s: prevent sleep while on AC power
    # -m: prevent disk idle sleep
    proc = subprocess.Popen([caffeinate_path, "-d", "-i", "-s", "-m"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def stop_process(proc):
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def send_f13():
    # Uses System Events. Requires Accessibility + Automation permissions.
    # AppleScript: tell application "System Events" to key code 105
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", f'tell application "System Events" to key code {F13_KEYCODE}'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        # If osascript itself fails, ignore; user will notice by behavior.
        pass


def get_random_datetime_in_window(day_date: dt.date, earliest_allowed: dt.datetime, window_start: dt.datetime, window_end: dt.datetime):
    min_start = window_start
    if earliest_allowed > min_start:
        min_start = earliest_allowed
    if min_start > window_end:
        return None
    span_seconds = int((window_end - min_start).total_seconds())
    if span_seconds < 0:
        return None
    offset = random.randint(0, span_seconds)
    return min_start + dt.timedelta(seconds=offset)


def get_next_session_start(win_start: dt.time, win_end: dt.time, allowed_days: list[str]):
    now = dt.datetime.now()
    # Search today + next 14 days
    for i in range(14):
        candidate_day = (now.date() + dt.timedelta(days=i))
        if day_abbrev(candidate_day) not in allowed_days:
            continue

        window_start = dt.datetime.combine(candidate_day, win_start)
        window_end = dt.datetime.combine(candidate_day, win_end)

        if window_end < window_start:
            raise ValueError("StartWindowEnd must be later than StartWindowStart (same day window).")

        earliest = dt.datetime.combine(candidate_day, dt.time.min)
        if i == 0:
            earliest = now

        candidate = get_random_datetime_in_window(candidate_day, earliest, window_start, window_end)
        if candidate is not None:
            return candidate

    raise RuntimeError("Could not find a valid next start time. Check your weekday list and time window.")


def run_session(min_minutes: int, max_minutes: int, interval_seconds: int):
    duration_minutes = random.randint(min_minutes, max_minutes)
    start_time = dt.datetime.now()
    end_time = start_time + dt.timedelta(minutes=duration_minutes)
    total_seconds = int((end_time - start_time).total_seconds())

    print(f"Session started: {dt_to_str(start_time)} | Duration: {duration_minutes} minutes | Ends: {dt_to_str(end_time)}")
    print("Controls while running: [E] end session early, [Q] quit script")

    next_send = dt.datetime.now()

    while True:
        now = dt.datetime.now()
        if now >= end_time:
            break

        key = read_key_nonblocking()
        if key == "Q":
            print("\nQuit requested.")
            sys.exit(0)
        if key == "E":
            print("\nEnding current session early. Waiting for next scheduled run.")
            break

        if now >= next_send:
            send_f13()
            next_send = now + dt.timedelta(seconds=interval_seconds)

        remaining_seconds = int((end_time - now).total_seconds())
        if remaining_seconds < 0:
            remaining_seconds = 0
        elapsed_seconds = total_seconds - remaining_seconds
        if elapsed_seconds < 0:
            elapsed_seconds = 0
        if elapsed_seconds > total_seconds:
            elapsed_seconds = total_seconds

        percent = 0
        if total_seconds > 0:
            percent = int((elapsed_seconds * 100) / total_seconds)

        print_progress_line("F13 session running", f"Remaining: {format_hhmmss(remaining_seconds)}", percent)
        # Match the Windows script's feel (fast progress updates) without burning CPU
        time_slice = 0.25
        select.select([], [], [], time_slice)

    clear_progress_line()
    print(f"Session ended: {dt_to_str(dt.datetime.now())}")


def wait_until(next_start: dt.datetime):
    print(f"Next session starts at: {dt_to_str(next_start)}")
    while True:
        now = dt.datetime.now()
        if now >= next_start:
            break

        key = read_key_nonblocking()
        if key == "Q":
            print("\nQuit requested.")
            sys.exit(0)

        remaining_seconds = int((next_start - now).total_seconds())
        if remaining_seconds < 0:
            remaining_seconds = 0

        status = f"Starts at {dt_to_str(next_start)} (in {format_hhmmss(remaining_seconds)})"
        print_progress_line("Waiting for next scheduled session", status, None)
        select.select([], [], [], 1.0)

    clear_progress_line()


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--start-window-start", default="08:30", help="Start of daily randomized start window (HH:MM or HH:MM:SS).")
    parser.add_argument("--start-window-end", default="10:00", help="End of daily randomized start window (HH:MM or HH:MM:SS).")
    parser.add_argument("--days-of-week", default="Mon,Tue,Wed,Thu,Fri", help="Comma-separated: Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    parser.add_argument("--min-duration-minutes", type=int, default=240, help="Minimum session duration (minutes).")
    parser.add_argument("--max-duration-minutes", type=int, default=480, help="Maximum session duration (minutes).")
    parser.add_argument("--interval-seconds", type=int, default=60, help="How often to send F13 during a session.")
    args = parser.parse_args()

    win_start = parse_time_of_day(args.start_window_start)
    win_end = parse_time_of_day(args.start_window_end)
    if dt.datetime.combine(dt.date.today(), win_end) < dt.datetime.combine(dt.date.today(), win_start):
        raise ValueError("StartWindowEnd must be later than StartWindowStart (same day window).")

    allowed_days = normalize_days(args.days_of_week)

    if args.min_duration_minutes <= 0 or args.max_duration_minutes <= 0:
        raise ValueError("Duration minutes must be > 0.")
    if args.max_duration_minutes < args.min_duration_minutes:
        raise ValueError("MaxDurationMinutes must be >= MinDurationMinutes.")
    if args.interval_seconds <= 0:
        raise ValueError("IntervalSeconds must be > 0.")

    # Start no-lock immediately and keep it active for the life of this script.
    caffeinate_proc = start_caffeinate()
    atexit.register(lambda: stop_process(caffeinate_proc))

    def handle_sigint(signum, frame):
        print("\nInterrupted. Exiting.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    print("No-lock is active (caffeinate running).")
    print("If F13 sending does not work, grant Accessibility and Automation permissions to your terminal app.")

    with RawTerminal():
        # Immediate run on launch
        run_session(args.min_duration_minutes, args.max_duration_minutes, args.interval_seconds)

        # Schedule future sessions forever
        while True:
            next_start = get_next_session_start(win_start, win_end, allowed_days)
            wait_until(next_start)
            run_session(args.min_duration_minutes, args.max_duration_minutes, args.interval_seconds)


if __name__ == "__main__":
    main()
