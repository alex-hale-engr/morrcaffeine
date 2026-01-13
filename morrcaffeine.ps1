# Randomized F13 keep-alive scheduler (immediate + scheduled) with progress + controls
# Keys during a session:
#   E = end current session early (skip to waiting)
#   Q = quit script
#
# Example:
# .\morrccaffeine.ps1 -StartWindowStart "08:30" -StartWindowEnd "10:00" -DaysOfWeek Mon,Tue,Wed,Thu,Fri -MinDurationMinutes 120 -MaxDurationMinutes 240 -IntervalSeconds 60

param(
    [Parameter(Mandatory=$false)]
    [string]$StartWindowStart = "08:30",

    [Parameter(Mandatory=$false)]
    [string]$StartWindowEnd = "10:00",

    [Parameter(Mandatory=$false)]
    [string[]]$DaysOfWeek = @("Mon","Tue","Wed","Thu","Fri"),

    [Parameter(Mandatory=$false)]
    [int]$MinDurationMinutes = 240,

    [Parameter(Mandatory=$false)]
    [int]$MaxDurationMinutes = 480,

    [Parameter(Mandatory=$false)]
    [int]$IntervalSeconds = 60
)

function Normalize-DayToken {
    param([string]$token)
    $t = $token.Trim().ToLower()
    if ($t.Length -ge 3) { $t = $t.Substring(0,3) }
    switch ($t) {
        "mon" { return "Mon" }
        "tue" { return "Tue" }
        "wed" { return "Wed" }
        "thu" { return "Thu" }
        "fri" { return "Fri" }
        "sat" { return "Sat" }
        "sun" { return "Sun" }
        default { return $null }
    }
}

function Day-Abbrev {
    param([datetime]$dt)
    switch ($dt.DayOfWeek) {
        "Monday"    { "Mon" }
        "Tuesday"   { "Tue" }
        "Wednesday" { "Wed" }
        "Thursday"  { "Thu" }
        "Friday"    { "Fri" }
        "Saturday"  { "Sat" }
        "Sunday"    { "Sun" }
    }
}

function Parse-TimeOfDay {
    param([string]$timeText)
    # Accepts "H:mm", "HH:mm", and optionally seconds.
    return [TimeSpan]::Parse($timeText, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-RandomDateTimeInWindow {
    param(
        [datetime]$dayDate,
        [datetime]$earliestAllowed,
        [datetime]$windowStart,
        [datetime]$windowEnd
    )

    $minStart = $windowStart
    if ($earliestAllowed -gt $minStart) { $minStart = $earliestAllowed }

    if ($minStart -gt $windowEnd) { return $null }

    $minSeconds = [int](($minStart - $dayDate).TotalSeconds)
    $maxSeconds = [int](($windowEnd - $dayDate).TotalSeconds)

    if ($maxSeconds -lt $minSeconds) { return $null }

    $offsetSeconds = Get-Random -Minimum $minSeconds -Maximum ($maxSeconds + 1)
    return $dayDate.AddSeconds($offsetSeconds)
}

function Get-NextSessionStart {
    param(
        [TimeSpan]$winStart,
        [TimeSpan]$winEnd,
        [string[]]$allowedDays
    )

    $now = Get-Date
    $normalizedAllowed = @()
    foreach ($d in $allowedDays) {
        $nd = Normalize-DayToken $d
        if ($nd) { $normalizedAllowed += $nd }
    }

    if ($normalizedAllowed.Count -eq 0) {
        throw "DaysOfWeek is empty or invalid. Use values like Mon,Tue,Wed,Thu,Fri,Sat,Sun."
    }

    for ($i = 0; $i -lt 14; $i++) {
        $candidateDay = $now.Date.AddDays($i)
        $dayAbbrev = Day-Abbrev $candidateDay

        if ($normalizedAllowed -notcontains $dayAbbrev) { continue }

        $windowStart = $candidateDay.Add($winStart)
        $windowEnd = $candidateDay.Add($winEnd)

        if ($windowEnd -lt $windowStart) {
            throw "StartWindowEnd must be later than StartWindowStart (same day window)."
        }

        $earliest = $candidateDay
        if ($i -eq 0) { $earliest = $now }

        $randomStart = Get-RandomDateTimeInWindow -dayDate $candidateDay -earliestAllowed $earliest -windowStart $windowStart -windowEnd $windowEnd
        if ($randomStart) { return $randomStart }
    }

    throw "Could not find a valid next start time. Check your weekday list and time window."
}

function Test-KeyPressed {
    param([string[]]$acceptKeys)

    if ([Console]::KeyAvailable) {
        $k = [Console]::ReadKey($true)
        $keyChar = ($k.KeyChar.ToString()).ToUpperInvariant()

        foreach ($ak in $acceptKeys) {
            if ($keyChar -eq $ak.ToUpperInvariant()) { return $keyChar }
        }
    }

    return $null
}

function Run-Session {
    param(
        [object]$shell,
        [int]$minMinutes,
        [int]$maxMinutes,
        [int]$intervalSeconds
    )

    $durationMinutes = Get-Random -Minimum $minMinutes -Maximum ($maxMinutes + 1)
    $startTime = Get-Date
    $endTime = $startTime.AddMinutes($durationMinutes)
    $totalSeconds = [int](($endTime - $startTime).TotalSeconds)

    Write-Host ("Session started: {0} | Duration: {1} minutes | Ends: {2}" -f $startTime.ToString("yyyy-MM-dd HH:mm:ss"), $durationMinutes, $endTime.ToString("yyyy-MM-dd HH:mm:ss"))
    Write-Host "Controls while running: [E] end session early, [Q] quit script"

    $nextKeySend = Get-Date

    while ($true) {
        $now = Get-Date
        if ($now -ge $endTime) { break }

        $pressed = Test-KeyPressed -acceptKeys @("E","Q")
        if ($pressed -eq "Q") {
            Write-Host "Quit requested."
            exit 0
        }
        if ($pressed -eq "E") {
            Write-Host "Ending current session early. Waiting for next scheduled run."
            break
        }

        if ($now -ge $nextKeySend) {
            $shell.SendKeys('{F13}')
            $nextKeySend = $now.AddSeconds($intervalSeconds)
        }

        $remainingSeconds = [int](($endTime - $now).TotalSeconds)
        if ($remainingSeconds -lt 0) { $remainingSeconds = 0 }

        $elapsedSeconds = $totalSeconds - $remainingSeconds
        if ($elapsedSeconds -lt 0) { $elapsedSeconds = 0 }
        if ($elapsedSeconds -gt $totalSeconds) { $elapsedSeconds = $totalSeconds }

        $percent = 0
        if ($totalSeconds -gt 0) {
            $percent = [int](($elapsedSeconds * 100) / $totalSeconds)
        }

        $remaining = [TimeSpan]::FromSeconds($remainingSeconds)
        $statusText = ("Remaining: {0:hh\:mm\:ss}" -f $remaining)

        Write-Progress -Activity "F13 session running" -Status $statusText -PercentComplete $percent
        Start-Sleep -Milliseconds 250
    }

    Write-Progress -Activity "F13 session running" -Completed
    Write-Host ("Session ended: {0}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
}

$windowStartSpan = Parse-TimeOfDay $StartWindowStart
$windowEndSpan = Parse-TimeOfDay $StartWindowEnd

if ($MinDurationMinutes -le 0 -or $MaxDurationMinutes -le 0) { throw "Duration minutes must be > 0." }
if ($MaxDurationMinutes -lt $MinDurationMinutes) { throw "MaxDurationMinutes must be >= MinDurationMinutes." }
if ($IntervalSeconds -le 0) { throw "IntervalSeconds must be > 0." }
if ($windowEndSpan -lt $windowStartSpan) { throw "StartWindowEnd must be later than StartWindowStart (same day window)." }

$wshell = New-Object -ComObject WScript.Shell

# Immediate run on launch
Run-Session -shell $wshell -minMinutes $MinDurationMinutes -maxMinutes $MaxDurationMinutes -intervalSeconds $IntervalSeconds

# Schedule future sessions forever
while ($true) {
    $nextStart = Get-NextSessionStart -winStart $windowStartSpan -winEnd $windowEndSpan -allowedDays $DaysOfWeek

    Write-Host ("Next session starts at: {0}" -f $nextStart.ToString("yyyy-MM-dd HH:mm:ss"))

    while ($true) {
        $now = Get-Date
        if ($now -ge $nextStart) { break }

        $pressed = Test-KeyPressed -acceptKeys @("Q")
        if ($pressed -eq "Q") {
            Write-Host "Quit requested."
            exit 0
        }

        $remainingSeconds = [int](($nextStart - $now).TotalSeconds)
        if ($remainingSeconds -lt 0) { $remainingSeconds = 0 }

        $remaining = [TimeSpan]::FromSeconds($remainingSeconds)
        Write-Progress `
            -Activity "Waiting for next scheduled session" `
            -Status ("Starts at {0} (in {1:hh\:mm\:ss})" -f $nextStart.ToString("yyyy-MM-dd HH:mm:ss"), $remaining) `
            -PercentComplete 0

        Start-Sleep -Seconds 1
    }

    Write-Progress -Activity "Waiting for next scheduled session" -Completed
    Run-Session -shell $wshell -minMinutes $MinDurationMinutes -maxMinutes $MaxDurationMinutes -intervalSeconds $IntervalSeconds
}
