#!/usr/bin/env python3
"""
morrcaffeine_macos.py

macOS port of the Windows morrcaffeine behavior:

- Always-on "no-lock" while the script runs (via /usr/bin/caffeinate).
- F13 scheduling behavior:
  * Run immediately on launch for a random duration between min/max.
  * Then schedule future sessions on selected weekdays:
      - Random start time inside a daily window
      - Random duration in range
      - Send F13 every N seconds during sessions

Controls (terminal must have focus):
- E : end current F13 session early (no-lock continues)
- Q : quit script (stops no-lock)

Notes:
- Sending F13 uses osascript/System Events (key code 105) and requires:
  * Privacy & Security -> Accessibility: allow your terminal app
  * Privacy & Security -> Automation: allow your terminal app to control "System Events"
"""

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
import shutil


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

F13_KEYCODE = 105  # macOS System Events key code for F13


def is_tty():
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except Exception:
        return False


class RawTerminal:
    """cbreak mode for single-key reads + optional terminal state toggles."""
    def __init__(self):
        self._fd = None
        self._old = None
        self._wrap_disabled = False

    def __enter__(self):
        if not sys.stdin.isatty():
            return self
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

        # Disable auto-wrap (prevents progress redraws from "spilling" into new lines).
        # Restore on exit.
        try:
            sys.stdout.write("\033[?7l")  # DECAWM off
            sys.stdout.flush()
            self._wrap_disabled = True
        except Exception:
            self._wrap_disabled = False

        return self

    def __exit__(self, exc_type, exc, tb):
        # Restore auto-wrap if we disabled it
        if self._wrap_disabled:
            try:
                sys.stdout.write("\033[?7h")  # DECAWM on
                sys.stdout.flush()
            except Exception:
                pass

        if self._fd is not None and self._old is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)


def normalize_days(days_csv):
    parts = [p.strip() for p in days_csv.split(",") if p.strip()]
    normalized = []
    for p in parts:
        key = p.lower()[:3]
        if key in DAY_MAP:
            normalized.append(DAY_MAP[key])
    if not normalized:
        raise ValueError("DaysOfWeek is empty or invalid. Use Mon,Tue,Wed,Thu,Fri,Sat,Sun.")
    return normalized


def parse_time_of_day(s):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    raise ValueError("Invalid time format. Use HH:MM or HH:MM:SS (e.g., 08:30).")


def day_abbrev(d):
    return DOW_ABBREV[d.weekday()]


def dt_to_str(x):
    return x.strftime("%Y-%m-%d %H:%M:%S")


def format_hhmmss(seconds):
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return "%02d:%02d:%02d" % (hh, mm, ss)


def _term_cols():
    try:
        return shutil.get_terminal_size(fallback=(80, 20)).columns
    except Exception:
        return 80


def print_progress_line(mode, remaining_seconds, percent):
    """
    Robust single-line progress display:
    - Clears the current line
    - Writes a short status that is always truncated to the terminal width
    - Never prints newlines
    """
    if not sys.stdout.isatty():
        return

    cols = _term_cols()
    if cols is None or cols < 20:
        cols = 80

    # Keep it deliberately short to avoid wrapping in narrow terminals.
    # Examples:
    #   RUN  06:03:50  [####------] 40%
    #   WAIT 10:19:05  (2026-01-22 08:47:12)
    if mode == "RUN":
        bar_width = 12
        done = int((percent / 100.0) * bar_width)
        done = max(0, min(done, bar_width))
        bar = "[" + ("#" * done) + ("-" * (bar_width - done)) + "]"
        line = "RUN  %s  %s %3d%%" % (format_hhmmss(remaining_seconds), bar, percent)
    else:
        # WAIT mode: remaining only; the caller prints the absolute start time once.
        line = "WAIT %s" % format_hhmmss(remaining_seconds)

    # Truncate aggressively: writing exactly the last column can still wrap in some terminals.
    max_len = max(10, cols - 2)
    if len(line) > max_len:
        line = line[:max_len]

    # CR + clear entire line + write
    sys.stdout.write("\r\033[2K" + line)
    sys.stdout.flush()


def clear_progress_line():
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\r\033[2K")
    sys.stdout.flush()


def read_key_nonblocking():
    """Return a single uppercase char if available, else None."""
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], 0)
    if not r:
        return None
    ch = os.read(sys.stdin.fileno(), 1)
    if not ch:
        return None
    try:
        return ch.decode("utf-8", errors="ignore").upper()
    except Exception:
        return None


def start_caffeinate():
    caffeinate_path = "/usr/bin/caffeinate"
    if not os.path.exists(caffeinate_path):
        raise RuntimeError("/usr/bin/caffeinate not found. This script requires macOS.")
    # -d prevent display sleep, -i prevent idle system sleep, -s prevent sleep on AC, -m prevent disk idle sleep
    return subprocess.Popen(
        [caffeinate_path, "-d", "-i", "-s", "-m"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_process(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def send_f13():
    # Requires Accessibility + Automation ("System Events") permissions for the terminal app.
    subprocess.run(
        ["/usr/bin/osascript", "-e", 'tell application "System Events" to key code %d' % F13_KEYCODE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def get_random_datetime_in_window(earliest_allowed, window_start, window_end):
    min_start = window_start if window_start > earliest_allowed else earliest_allowed
    if min_start > window_end:
        return None
    span_seconds = int((window_end - min_start).total_seconds())
    if span_seconds < 0:
        return None
    offset = random.randint(0, span_seconds)
    return min_start + dt.timedelta(seconds=offset)


def get_next_session_start(win_start, win_end, allowed_days):
    now = dt.datetime.now()
    # Search today + next 14 days
    for i in range(14):
        day = now.date() + dt.timedelta(days=i)
        if day_abbrev(day) not in allowed_days:
            continue

        ws = dt.datetime.combine(day, win_start)
        we = dt.datetime.combine(day, win_end)
        if we < ws:
            raise ValueError("StartWindowEnd must be later than StartWindowStart (time windows do not cross midnight).")

        earliest = now if i == 0 else dt.datetime.combine(day, dt.time.min)
        candidate = get_random_datetime_in_window(earliest, ws, we)
        if candidate is not None:
            return candidate

    raise RuntimeError("Could not find a valid next session start. Check days and time window.")


def run_session(min_minutes, max_minutes, interval_seconds, progress_tick_seconds):
    duration = random.randint(min_minutes, max_minutes)
    start = dt.datetime.now()
    end = start + dt.timedelta(minutes=duration)
    total = int((end - start).total_seconds())

    print("Session started: %s | Duration: %d minutes | Ends: %s" % (dt_to_str(start), duration, dt_to_str(end)))
    print("Controls while running: [E] end session early, [Q] quit")

    next_send = dt.datetime.now()
    next_progress = dt.datetime.now()

    while True:
        now = dt.datetime.now()
        if now >= end:
            break

        key = read_key_nonblocking()
        if key == "Q":
            clear_progress_line()
            print("\nExiting.")
            sys.exit(0)
        if key == "E":
            clear_progress_line()
            print("\nEnding current session early. Waiting for next scheduled session.")
            break

        if now >= next_send:
            send_f13()
            next_send = now + dt.timedelta(seconds=interval_seconds)

        if now >= next_progress:
            remaining = int((end - now).total_seconds())
            if remaining < 0:
                remaining = 0
            elapsed = total - remaining
            if elapsed < 0:
                elapsed = 0
            if elapsed > total:
                elapsed = total
            percent = int((elapsed * 100) / total) if total > 0 else 0

            print_progress_line("RUN", remaining, percent)
            next_progress = now + dt.timedelta(seconds=progress_tick_seconds)

        # small sleep to avoid busy looping, while staying responsive to keypresses
        select.select([], [], [], 0.10)

    clear_progress_line()
    print("Session ended: %s" % dt_to_str(dt.datetime.now()))


def wait_until(next_start, progress_tick_seconds):
    print("Next session starts at: %s" % dt_to_str(next_start))
    next_progress = dt.datetime.now()

    while True:
        now = dt.datetime.now()
        if now >= next_start:
            break

        key = read_key_nonblocking()
        if key == "Q":
            clear_progress_line()
            print("\nExiting.")
            sys.exit(0)

        if now >= next_progress:
            remaining = int((next_start - now).total_seconds())
            if remaining < 0:
                remaining = 0
            print_progress_line("WAIT", remaining, 0)
            next_progress = now + dt.timedelta(seconds=progress_tick_seconds)

        select.select([], [], [], 0.20)

    clear_progress_line()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start-window-start", default="08:30")
    p.add_argument("--start-window-end", default="10:00")
    p.add_argument("--days-of-week", default="Mon,Tue,Wed,Thu,Fri")
    p.add_argument("--min-duration-minutes", type=int, default=240)
    p.add_argument("--max-duration-minutes", type=int, default=480)
    p.add_argument("--interval-seconds", type=int, default=60)
    p.add_argument("--progress-tick-seconds", type=int, default=1, help="How often to refresh the progress display (seconds). Default 1.")
    args = p.parse_args()

    win_start = parse_time_of_day(args.start_window_start)
    win_end = parse_time_of_day(args.start_window_end)

    # Validate same-day window (no midnight crossing)
    today = dt.date.today()
    if dt.datetime.combine(today, win_end) < dt.datetime.combine(today, win_start):
        raise ValueError("StartWindowEnd must be later than StartWindowStart (time windows do not cross midnight).")

    allowed_days = normalize_days(args.days_of_week)

    if args.min_duration_minutes <= 0 or args.max_duration_minutes <= 0:
        raise ValueError("Duration minutes must be > 0.")
    if args.max_duration_minutes < args.min_duration_minutes:
        raise ValueError("MaxDurationMinutes must be >= MinDurationMinutes.")
    if args.interval_seconds <= 0:
        raise ValueError("IntervalSeconds must be > 0.")
    if args.progress_tick_seconds <= 0:
        raise ValueError("progress-tick-seconds must be > 0.")

    # Always-on no-lock
    caffeinate_proc = start_caffeinate()
    atexit.register(lambda: stop_process(caffeinate_proc))

    def handle_sig(*_):
        clear_progress_line()
        print("\nExiting.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    print("No-lock active via caffeinate.")
    print("If F13 does not work: allow your terminal in Privacy & Security -> Accessibility and Automation (System Events).")

    with RawTerminal():
        # Immediate session on launch
        run_session(args.min_duration_minutes, args.max_duration_minutes, args.interval_seconds, args.progress_tick_seconds)

        # Then scheduled sessions forever
        while True:
            next_start = get_next_session_start(win_start, win_end, allowed_days)
            wait_until(next_start, args.progress_tick_seconds)
            run_session(args.min_duration_minutes, args.max_duration_minutes, args.interval_seconds, args.progress_tick_seconds)


if __name__ == "__main__":
    main()
