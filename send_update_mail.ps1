param(
    [string]$To = "sales@heungaline.co.th",
    [switch]$NoAttach,
    [switch]$DraftOnly
)
# Sends the daily HCM mail through the desktop Outlook profile that is signed in (no password is stored).
# Subject and body are prepared by build_hcm_schedule.py --mail-body (output\mail_subject.txt / mail_body.html).
# -DraftOnly saves it to Drafts instead of sending.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$subject = [System.IO.File]::ReadAllText((Join-Path $here "output\mail_subject.txt"), [System.Text.Encoding]::UTF8).Trim()
$body    = [System.IO.File]::ReadAllText((Join-Path $here "output\mail_body.html"), [System.Text.Encoding]::UTF8)

$ol = New-Object -ComObject Outlook.Application
$m = $ol.CreateItem(0)
$m.To = $To
$m.Subject = $subject
$m.HTMLBody = $body
# attach the dashboard page itself (self-contained: opens by double-click, no server needed)
$page = Join-Path $here "output\hcm_schedule_dashboard.html"
if ((Test-Path $page) -and -not $NoAttach) {
    $copy = Join-Path $env:TEMP ("HCM_Schedule_" + (Get-Date -Format "yyyy-MM-dd") + ".html")
    Copy-Item $page $copy -Force
    [void]$m.Attachments.Add($copy)
}
if ($DraftOnly) { $m.Save(); "saved draft: $subject" } else { $m.Send(); "sent: $subject" }
