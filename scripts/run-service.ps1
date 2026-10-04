param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('portal', 'caddy')]
    [string]$Service,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

try {
    # Parse literal KEY=value entries; never execute the .env contents.
    $envFile = Join-Path $projectRoot '.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            $entry = $line.Trim()
            if (-not $entry -or $entry.StartsWith('#')) { continue }
            if ($entry -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
                throw 'Invalid .env entry. Use KEY=value lines.'
            }
            $entryKey = $Matches[1]
            $entryValue = $Matches[2].Trim()
            if ($entryValue.Length -ge 2 -and (
                ($entryValue.StartsWith('"') -and $entryValue.EndsWith('"')) -or
                ($entryValue.StartsWith("'") -and $entryValue.EndsWith("'")))) {
                $entryValue = $entryValue.Substring(1, $entryValue.Length - 2)
            }
            if ($null -eq [Environment]::GetEnvironmentVariable($entryKey, 'Process')) {
                [Environment]::SetEnvironmentVariable($entryKey, $entryValue, 'Process')
            }
        }
    }
    if ($Service -eq 'portal') {
        $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Project virtual environment is missing. See README.md.' }
        if ($CheckOnly) { Write-Host 'Portal launcher configuration OK.'; exit 0 }
        & $pythonExe (Join-Path $projectRoot 'run.py')
    } else {
        $caddyExe = $env:CADDY_EXE
        if (-not $caddyExe) {
            foreach ($candidate in @((Join-Path $projectRoot 'caddy.exe'), (Join-Path $projectRoot 'bin\caddy.exe'))) {
                if (Test-Path -LiteralPath $candidate) { $caddyExe = $candidate; break }
            }
        }
        if (-not $caddyExe) {
            $command = Get-Command caddy.exe -ErrorAction SilentlyContinue
            if ($command) { $caddyExe = $command.Source }
        }
        if (-not $caddyExe) { throw 'Caddy is missing. Download caddy.exe from https://caddyserver.com/download and place it beside start.bat, or set CADDY_EXE in .env.' }
        $configFile = Join-Path $projectRoot 'Caddyfile'
        & $caddyExe validate --config $configFile --adapter caddyfile
        if ($LASTEXITCODE -ne 0) { throw 'Caddyfile validation failed.' }
        if ($CheckOnly) { Write-Host 'Caddy launcher configuration OK.'; exit 0 }
        & $caddyExe run --config $configFile --adapter caddyfile
    }
    if ($LASTEXITCODE -ne 0) { throw "$Service exited with code $LASTEXITCODE." }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
