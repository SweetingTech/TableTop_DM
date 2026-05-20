param(
    [string]$Version = "v1.0.0",
    [string]$Mode = "git"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseDir = Join-Path $Root "release"
$ZipPath = Join-Path $ReleaseDir "TableTopDM-$Version.zip"
$ChecksumPath = Join-Path $ReleaseDir "checksums.txt"

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

Push-Location $Root
try {
    if ($Mode -eq "git") {
        git archive --format=zip --output $ZipPath HEAD
    } else {
        $Temp = Join-Path $env:TEMP "tabletopdm-release-$Version"
        if (Test-Path $Temp) { Remove-Item -Recurse -Force $Temp }
        New-Item -ItemType Directory -Force -Path $Temp | Out-Null
        Get-ChildItem -Force $Root |
            Where-Object {
                $_.Name -notin @(".git", ".venv", "__pycache__", "data", "burn-bag", ".local-run", ".run", "release")
            } |
            ForEach-Object {
                Copy-Item -Recurse -Force -LiteralPath $_.FullName -Destination $Temp
            }
        Compress-Archive -Path (Join-Path $Temp "*") -DestinationPath $ZipPath -Force
        Remove-Item -Recurse -Force $Temp
    }

    $Hash = Get-FileHash -Algorithm SHA256 $ZipPath
    "$($Hash.Hash)  $(Split-Path -Leaf $ZipPath)" | Set-Content -Encoding UTF8 $ChecksumPath
    Write-Host "[package] wrote $ZipPath"
    Write-Host "[package] wrote $ChecksumPath"
} finally {
    Pop-Location
}
