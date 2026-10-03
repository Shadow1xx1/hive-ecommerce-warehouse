Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI not found. Install/start Docker Desktop, then rerun this script.'
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $projectRoot
try {
    & docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed.' }

    $jdbcUrl = 'jdbc:hive2://localhost:10000/'
    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        # PowerShell 5.1 may treat expected connection errors on stderr as
        # terminating errors while $ErrorActionPreference is Stop.
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & docker compose exec -T hive beeline -u $jdbcUrl -e 'SHOW DATABASES;' *> $null
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 5
    }
    if (-not $ready) { throw 'HiveServer2 did not become ready. Inspect: docker compose logs hive' }

    $files = @(
        '01_create_tables.sql',
        '02_load_raw.sql',
        '03_build_dwd.sql',
        '04_build_dws.sql',
        '05_build_ads.sql',
        '06_quality_checks.sql',
        '07_assert_quality.sql'
    )
    foreach ($file in $files) {
        Write-Host "Running $file"
        & docker compose exec -T hive beeline -u $jdbcUrl -f "/project/sql/$file"
        if ($LASTEXITCODE -ne 0) { throw "Hive failed while running $file" }
    }
    Write-Host 'Pipeline finished. Compare dashboard rows with data/expected_dashboard.csv.'
}
finally {
    Pop-Location
}

