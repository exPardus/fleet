# Polls the roster every 10 min; logs presence of the named m0 session.
param([string]$Name = "m0-reap", [int]$Hours = 2)
$log = "C:\proga\claude-fleet\spike\m0\out\reap_watch.log"
$deadline = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $deadline) {
    $json = claude agents --json --all | Out-String
    $found = $json -match $Name
    Add-Content $log ("{0}  present={1}" -f (Get-Date -Format o), $found)
    Start-Sleep -Seconds 600
}
