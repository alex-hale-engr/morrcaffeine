# morrcaffeine_macos.py

## Overview
morrcaffeine_macos.py is a macOS port of the Windows morrcaffeine script behavior.

It provides two independent functions:
1) Always-on no-lock while the script is running (no input events)
2) F13 keypress scheduling with the same behavior as the Windows script:
   - Immediate session on launch (random duration in range)
   - Then scheduled sessions on selected weekdays
   - Random start time inside a daily window
   - Random duration per session
   - Fixed F13 interval during sessions
   - Live countdown progress output
   - Interactive controls to end session or quit

This is intended to prevent macOS from sleeping or locking due to idle while avoiding fake mouse movement. F13 sending is still optional behavior to match the original script scheduling.

---

## Requirements
- macOS
- Python 3.9+ (Apple system Python is often restricted; use python3 from Xcode CLT or Homebrew)
- /usr/bin/caffeinate (included with macOS)

For F13 sending:
- macOS Accessibility permission for your terminal app (Terminal or iTerm2)
- macOS Automation permission for your terminal app to control "System Events" (prompted on first run)

---

## Install
Download morrcaffeine_macos.py and make it executable:

```bash
chmod +x morrcaffeine_macos.py
```

---

## Usage

### Example
```bash
./morrcaffeine_macos.py --start-window-start 08:30 --start-window-end 10:00 --days-of-week Mon,Tue,Wed,Thu,Fri --min-duration-minutes 120 --max-duration-minutes 240 --interval-seconds 60
```

### Default run
```bash
./morrcaffeine_macos.py
```

Defaults:
- Start window: 08:30 to 10:00
- Days: Mon,Tue,Wed,Thu,Fri
- Duration: 240 to 480 minutes
- Interval: 60 seconds

---

## Parameters
- --start-window-start
  Start of the daily randomized start window (HH:MM or HH:MM:SS). Default: 08:30

- --start-window-end
  End of the daily randomized start window (HH:MM or HH:MM:SS). Default: 10:00
  Must be later than start (time windows do not cross midnight).

- --days-of-week
  Comma-separated list of allowed days. Example: Mon,Tue,Wed,Thu,Fri
  Valid: Mon,Tue,Wed,Thu,Fri,Sat,Sun

- --min-duration-minutes
  Minimum session duration in minutes. Default: 240

- --max-duration-minutes
  Maximum session duration in minutes. Default: 480
  Must be >= min duration.

- --interval-seconds
  How often to send F13 during a session. Default: 60

---

## No-lock behavior (always on)
When the script starts, it launches:
- /usr/bin/caffeinate -d -i -s -m

This creates an IOKit power assertion that prevents idle sleep and display sleep while the script runs.
It does NOT generate keyboard or mouse input events.
When the script exits, caffeinate is terminated and normal behavior resumes.

Important:
- caffeinate does not necessarily stop a screen saver that is configured to lock the screen without sleep.
  If your Mac locks via screen saver policy, adjust System Settings accordingly.

---

## F13 sending behavior
During sessions, the script sends F13 using:
- /usr/bin/osascript with System Events key code 105 (F13)

This requires permissions:
1) System Settings -> Privacy & Security -> Accessibility
   - Allow your terminal app (Terminal or iTerm2)

2) System Settings -> Privacy & Security -> Automation
   - Allow your terminal app to control "System Events"
   - macOS will typically prompt you on first run

If permissions are not granted, the no-lock function will still work, but F13 keypresses may not be delivered.

---

## Controls
During a session:
- E = end current F13 session early and wait for the next scheduled session
- Q = quit the script immediately

While waiting:
- Q = quit the script immediately

Controls require that the terminal running the script has focus.

---

## Output
The script prints:
- Session start, duration, and end timestamp
- Next session start timestamp
- Live countdown progress output for running and waiting

---

## Notes and limitations
- Time windows do not cross midnight.
- If your terminal is not a TTY (for example, launched as a background job without a terminal), interactive controls may not work.
- Corporate policies may override idle behavior or require lock regardless of system sleep settings.

---

## Disclaimer
Use responsibly and in accordance with your organization policies.
