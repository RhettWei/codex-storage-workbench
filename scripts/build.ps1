param([string]$Python='python')
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --onedir --name CodexStorageWorkbench run.py
    if($LASTEXITCODE){throw 'PyInstaller build failed'}
    $destination=Join-Path $projectRoot 'dist\CodexStorageWorkbench'
    foreach($file in @('README.md','LICENSE','NOTICE.md','UPSTREAM.md','VALIDATION.md')){
        Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $destination -Force
    }
    $licenseDestination=Join-Path $destination 'licenses'
    New-Item -ItemType Directory -Path $licenseDestination -Force | Out-Null
    $basePython=& $Python -c "import sys;print(sys.base_prefix)"
    Copy-Item -LiteralPath (Join-Path $basePython 'LICENSE.txt') -Destination (Join-Path $licenseDestination 'Python-LICENSE.txt') -Force
    foreach($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'licenses') -File){
        Copy-Item -LiteralPath $file.FullName -Destination $licenseDestination -Force
    }
    $launcher=@('@echo off','cd /d "%~dp0"','start "" "%~dp0CodexStorageWorkbench.exe" --state-dir "%~dp0local-state" gui','') -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $destination 'Start.cmd'),$launcher,[Text.Encoding]::ASCII)
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'release') -Force | Out-Null
    $zip=Join-Path $projectRoot 'release\CodexStorageWorkbench-0.2.0.dev1-Windows-x64.zip'
    Compress-Archive -Path (Join-Path $destination '*') -DestinationPath $zip -Force
    $hash=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath (Join-Path $projectRoot 'release\SHA256SUMS.txt') -Encoding ascii
} finally {Pop-Location}
