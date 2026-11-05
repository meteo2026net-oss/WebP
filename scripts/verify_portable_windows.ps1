[CmdletBinding()]
param(
    [ValidateRange(3, 60)]
    [int]$StartupSeconds = 8,

    [ValidateRange(5, 90)]
    [int]$MapTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$script:HasFailures = $false
$script:Checks = New-Object 'System.Collections.Generic.List[string]'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$exe = Join-Path $root "ECMWFWebP.exe"
$launcher = Join-Path $root "START.bat"
$manifest = Join-Path $root "SHA256SUMS.txt"
$reportRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "ECMWFWebP\logs"
} else {
    Join-Path $env:TEMP "ECMWFWebP\logs"
}
$reportPath = Join-Path $reportRoot ("portable-acceptance-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
$appProcess = $null
$mapProcess = $null
$httpClient = $null

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $prefix = if ($Passed) { "PASS" } else { "FAIL" }
    $line = "$prefix | $Name | $Detail"
    [void]$script:Checks.Add($line)
    if (-not $Passed) {
        $script:HasFailures = $true
        Write-Host $line -ForegroundColor Red
    } else {
        Write-Host $line -ForegroundColor Green
    }
}

function Get-UploadableFiles {
    param([string]$PackageRoot)
    $prefix = $PackageRoot.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
    $result = @()
    foreach ($file in Get-ChildItem -LiteralPath $PackageRoot -File -Recurse) {
        if ($file.Name -eq "SHA256SUMS.txt") { continue }
        $relative = $file.FullName.Substring($prefix.Length)
        $segments = $relative -split '[\\/]'
        $hidden = $false
        foreach ($segment in $segments) {
            if ($segment.StartsWith(".")) { $hidden = $true; break }
        }
        if (-not $hidden) { $result += $relative }
    }
    return $result
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-HttpResult {
    param([System.Net.Http.HttpClient]$Client, [string]$Uri)
    $response = $Client.GetAsync($Uri).GetAwaiter().GetResult()
    try {
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $body }
    } finally {
        $response.Dispose()
    }
}

try {
    $isWindows = ($env:OS -eq "Windows_NT")
    $is64Bit = [Environment]::Is64BitOperatingSystem
    Add-Check "Operating system" ($isWindows -and $is64Bit) "Windows=$isWindows; 64-bit=$is64Bit; PowerShell=$($PSVersionTable.PSVersion)"

    foreach ($required in @($exe, $launcher, $manifest)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required package file is missing: $([IO.Path]::GetFileName($required))"
        }
    }
    Add-Check "Portable package files" $true "EXE, START.bat, and SHA256SUMS.txt are present"

    $listed = @{}
    foreach ($line in [IO.File]::ReadAllLines($manifest)) {
        if ($line.Length -lt 67 -or $line.Substring(64, 2) -ne "  ") {
            throw "Invalid SHA256 manifest line."
        }
        $expectedHash = $line.Substring(0, 64).ToLowerInvariant()
        $relative = $line.Substring(66)
        if ($expectedHash -notmatch '^[0-9a-f]{64}$') { throw "Invalid SHA256 value in package manifest." }
        if ($listed.ContainsKey($relative)) { throw "Duplicate SHA256 manifest entry." }
        $filePath = Join-Path $root $relative
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "A file listed in SHA256SUMS.txt is missing." }
        $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) { throw "A package file does not match its SHA-256 value: $relative" }
        $listed[$relative] = $expectedHash
    }

    $actualFiles = @(Get-UploadableFiles -PackageRoot $root)
    if ($listed.Count -ne $actualFiles.Count) { throw "The manifest does not cover exactly all uploadable package files." }
    foreach ($relative in $actualFiles) {
        if (-not $listed.ContainsKey($relative)) { throw "A package file is not covered by SHA256SUMS.txt: $relative" }
    }
    Add-Check "SHA-256 package integrity" $true "$($listed.Count) files verified; no missing, extra, or mismatched entries"

    $dataRoot = if ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA "ECMWFWebP"
    } else {
        Join-Path $env:TEMP "ECMWFWebP"
    }
    $logRoot = Join-Path $dataRoot "logs"
    [void](New-Item -ItemType Directory -Path $logRoot -Force)
    $probe = Join-Path $logRoot (".write-probe-" + [guid]::NewGuid().ToString("N") + ".tmp")
    [IO.File]::WriteAllText($probe, "ECMWFWebP write test")
    Remove-Item -LiteralPath $probe -Force
    Add-Check "User data directory" $true "The per-user application data directory is writable"

    $appProcess = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    Start-Sleep -Seconds $StartupSeconds
    $appProcess.Refresh()
    if ($appProcess.HasExited) { throw "The packaged desktop application exited during startup (code $($appProcess.ExitCode))." }
    Add-Check "Desktop application startup" $true "The packaged GUI remained running for $StartupSeconds seconds"

    $baseUri = "http://127.0.0.1:8765"
    if (-not (Test-TcpPort -HostName "127.0.0.1" -Port 8765)) {
        $mapProcess = Start-Process -FilePath $exe -ArgumentList @("--map-server", "--no-browser") -WorkingDirectory $root -PassThru -WindowStyle Hidden
    }

    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $httpClient = New-Object System.Net.Http.HttpClient($handler)
    $httpClient.Timeout = [TimeSpan]::FromSeconds(4)

    $ready = $false
    $lastFailure = "Map server did not respond"
    for ($attempt = 0; $attempt -lt $MapTimeoutSeconds; $attempt++) {
        try {
            $page = Get-HttpResult -Client $httpClient -Uri "$baseUri/map_viewer/"
            if ($page.Status -eq 200 -and $page.Body.Contains("ECMWF Weather Map")) {
                $ready = $true
                break
            }
            $lastFailure = "Map viewer returned HTTP $($page.Status) or unexpected HTML"
        } catch {
            $lastFailure = $_.Exception.GetBaseException().Message
        }

        if ($mapProcess) {
            $mapProcess.Refresh()
            if ($mapProcess.HasExited) { throw "The packaged map server exited during startup (code $($mapProcess.ExitCode))." }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "The local map viewer did not become ready: $lastFailure" }

    foreach ($asset in @("style.css", "app.js")) {
        $result = Get-HttpResult -Client $httpClient -Uri "$baseUri/map_viewer/$asset"
        if ($result.Status -ne 200 -or [string]::IsNullOrWhiteSpace($result.Body)) {
            throw "The map viewer asset failed its HTTP check: $asset (HTTP $($result.Status))."
        }
    }
    Add-Check "Bundled map server" $true "Map HTML, CSS, and JavaScript responded successfully on localhost:8765"
    Add-Check "Credential privacy" $true "This preflight does not read, print, or transmit ECMWF/PostgreSQL credentials"
} catch {
    Add-Check "Acceptance preflight" $false $_.Exception.GetBaseException().Message
} finally {
    if ($httpClient) { $httpClient.Dispose() }
    if ($mapProcess -and -not $mapProcess.HasExited) {
        Stop-Process -Id $mapProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($appProcess -and -not $appProcess.HasExited) {
        [void]$appProcess.CloseMainWindow()
        if (-not $appProcess.WaitForExit(5000)) {
            Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }

    [void](New-Item -ItemType Directory -Path $reportRoot -Force)
    $header = @(
        "ECMWFWebP portable acceptance report",
        "Generated UTC: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
        "Windows 64-bit: $([Environment]::Is64BitOperatingSystem)",
        "PowerShell: $($PSVersionTable.PSVersion)",
        "No credentials or connection strings are included.",
        ""
    )
    @($header + $script:Checks) | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host ""
    Write-Host "Report saved to the local application logs folder." -ForegroundColor Cyan
}

if ($script:HasFailures) { exit 1 }
Write-Host "ECMWFWebP portable acceptance preflight PASSED." -ForegroundColor Green
exit 0
