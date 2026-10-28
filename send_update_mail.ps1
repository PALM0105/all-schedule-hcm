param(
    [ValidateSet("ok","nochange","failed")][string]$Result = "ok",
    [string]$To = "sales@heungaline.co.th",
    [switch]$DraftOnly
)
# Sends the daily HCM schedule update mail through the desktop Outlook profile that is signed in
# (no password is stored anywhere). -DraftOnly saves it to Drafts instead of sending.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$url  = "https://palm0105.github.io/all-schedule-hcm/dashboard.html"
$cache = Join-Path $here "output\_cache.json"
$date = Get-Date -Format "dd MMM yyyy HH:mm"

$rows = ""; $merged = ""; $bad = @()
if (Test-Path $cache) {
    $c = Get-Content $cache -Raw -Encoding UTF8 | ConvertFrom-Json
    $merged = $c.merged
    foreach ($s in $c.statuses) {
        $color = if ($s.Status -eq "ok") { "#15803d" } else { "#b91c1c" }
        if ($s.Status -ne "ok") { $bad += $s.Source }
        $rows += "<tr><td style='padding:3px 12px 3px 0'>$($s.Source)</td><td style='padding:3px 12px 3px 0;color:$color'><b>$($s.Status)</b></td><td style='padding:3px 0'>$($s.Sailings) sailings</td></tr>"
    }
}

switch ($Result) {
    "failed"   { $subject = "[HCM Schedule] Update FAILED - $date"; $lead = "<p style='color:#b91c1c'><b>The scheduled update failed.</b> The website still shows the previous data. Details are in update_log.txt on the update PC.</p>" }
    "nochange" { $subject = "[HCM Schedule] Updated, no changes - $date"; $lead = "<p>The schedule was refreshed. Nothing changed since the last update.</p>" }
    default    { $subject = "[HCM Schedule] Updated - $date"; $lead = "<p>The Bangkok / Laem Chabang to Ho Chi Minh City schedule was refreshed and published.</p>" }
}
$note = ""
if ($bad.Count -gt 0) { $note = "<p style='color:#64748b'>Not available this run: $($bad -join ', ').</p>" }
$total = if ($merged) { "<p><b>$merged</b> sailings after merging duplicate vessels.</p>" } else { "" }

$body = "<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px'>$lead$total" +
        "<table style='border-collapse:collapse'>$rows</table>$note" +
        "<p><a href='$url'>Open the dashboard</a><br><span style='color:#64748b'>$url</span></p>" +
        "<p style='color:#94a3b8;font-size:12px'>Automatic message from the HCM schedule updater.</p></div>"

$ol = New-Object -ComObject Outlook.Application
$m = $ol.CreateItem(0)
$m.To = $To
$m.Subject = $subject
$m.HTMLBody = $body
if ($DraftOnly) { $m.Save(); "saved draft: $subject" } else { $m.Send(); "sent: $subject" }
