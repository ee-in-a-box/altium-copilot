param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if (-not $SkipBuild) {
    Write-Host 'Building binary...' -ForegroundColor Cyan
    & "$root\.venv\Scripts\pyinstaller.exe" `
        --onefile `
        --name altium-copilot `
        --distpath "$root\server\dist" `
        --workpath "$root\build" `
        --add-data "$root\server\scripts;scripts" `
        --add-data "$root\manifest.json;." `
        --paths "$root\server" `
        "$root\server\main.py"
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
}

$exe = "$root\server\dist\altium-copilot.exe"
if (-not (Test-Path $exe)) { throw "Binary not found at $exe. Run without -SkipBuild." }

$stage = "$root\dist\stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\server\dist" | Out-Null
New-Item -ItemType Directory -Path "$stage\assets" | Out-Null

Copy-Item "$root\manifest.json" "$stage\manifest.json"
Copy-Item $exe "$stage\server\dist\altium-copilot.exe"

$icon = "$root\assets\icon.png"
if (Test-Path $icon) {
    Copy-Item $icon "$stage\assets\icon.png"
} else {
    Write-Warning 'assets/icon.png not found. Create a 512x512 PNG before submitting to the directory.'
}

# --- Validate manifest against Anthropic's schema before packing ---
Write-Host 'Validating manifest...' -ForegroundColor Cyan
npx --yes @anthropic-ai/mcpb validate "$stage\manifest.json"
if ($LASTEXITCODE -ne 0) { throw 'mcpb validate failed. Fix manifest.json before packing.' }

$version = (Get-Content "$root\manifest.json" -Raw | ConvertFrom-Json).version
$out = "$root\dist\altium-copilot-$version.mcpb"
if (Test-Path $out) { Remove-Item $out -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $out)

$sizeMb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host ''
Write-Host "Packaged: $out" -ForegroundColor Green
Write-Host "Size:     $sizeMb MB"
Write-Host ''
Write-Host 'Next: drag the .mcpb onto Claude Desktop Settings -> Extensions -> Install Extension'
