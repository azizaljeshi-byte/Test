# Run this yourself after merging and configuring the private Google settings.
param(
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$Database = (Join-Path $env:LOCALAPPDATA 'StockWatch\smallcap.db')
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = (Resolve-Path $Python).Path
$Database = [System.IO.Path]::GetFullPath($Database)
New-Item -ItemType Directory -Force -Path (Split-Path $Database) | Out-Null
$Action = New-ScheduledTaskAction -Execute $Python `
    -Argument ('-m stockwatch.smallcap --db "{0}"' -f $Database) -WorkingDirectory $Repo
# Indefinite hourly trigger in PC local time. Python checks the NY session, including DST.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'StockWatch Smallcap' -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal -Description 'Hourly smallcap Sheet; Python gates the New York session.'
