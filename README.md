# morrccaffeine.ps1

## Based on https://www.zhornsoftware.co.uk/caffeine/ which was blocked at a corporate level, but I could still run a powershell script.  I wanted more randomness and flexibility in duration, didn't need a GUI, and I wanted it to be able to run forever in the background on its own without requiring me to physically start it every day.

## Overview
morrccaffeine.ps1 is a randomized F13 keep-alive script for Windows. It periodically sends an F13 keypress to prevent idle or lock behavior.

The script is designed to:
- Run immediately on launch
- Schedule future sessions on selected weekdays
- Randomize both start time and duration
- Provide a live countdown progress bar
- Allow manual control during execution

---

## Features
- Sends F13 at a fixed interval (non-conflicting key)
- Immediate session on startup
- Randomized daily start time within a configurable window
- Runs only on selected weekdays
- Randomized session duration within min and max bounds
- Countdown progress bar during sessions
- Interactive controls (end session or quit)
- No external dependencies

---

## Requirements
- Windows PowerShell 5.1 or PowerShell 7+
- Script execution enabled for local scripts

---

## Usage

### Basic run
```powershell
.\morrccaffeine.ps1
```

### Example with custom parameters
```powershell
.\morrccaffeine.ps1 `
  -StartWindowStart "08:30" `
  -StartWindowEnd "10:00" `
  -DaysOfWeek Mon,Tue,Wed,Thu,Fri `
  -MinDurationMinutes 120 `
  -MaxDurationMinutes 240 `
  -IntervalSeconds 60
```

---

## Parameters

### -StartWindowStart
Start of the daily randomized start window (time of day).
- Default: 08:30
- Accepts H:mm, HH:mm, optional seconds

### -StartWindowEnd
End of the daily randomized start window (time of day).
- Default: 10:00
- Must be later than StartWindowStart

### -DaysOfWeek
Days eligible for scheduled sessions.
- Default: Mon,Tue,Wed,Thu,Fri
- Valid values: Mon Tue Wed Thu Fri Sat Sun

### -MinDurationMinutes
Minimum duration of a session, in minutes.
- Default: 240

### -MaxDurationMinutes
Maximum duration of a session, in minutes.
- Default: 480
- Must be greater than or equal to MinDurationMinutes

### -IntervalSeconds
How often F13 is sent during a session.
- Default: 60

---

## Runtime Controls

While a session is running:
- E - End the current session early and wait for the next scheduled session
- Q - Quit the script immediately

While waiting for the next scheduled session:
- Q - Quit the script

Note: These controls require the PowerShell window to have focus.

---

## Output Behavior

### During a session
- Displays start time, duration, and end time
- Shows a progress bar with remaining time

### Between sessions
- Prints the absolute date and time of the next session
- Shows a countdown progress bar until the next start

---

## Running Hidden (Optional)
To run without a visible PowerShell window, create a shortcut with this target:
```powershell
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\path\morrccaffeine.ps1"
```

Note: When hidden, interactive key controls and progress bars will not be visible.

---

## Notes
- F13 is a valid virtual key in Windows, even if your keyboard does not have a physical F13 key.
- The script runs indefinitely until you quit it.
- Time windows do not cross midnight.

---

## License and Disclaimer
Use responsibly and in accordance with your organization policies.
