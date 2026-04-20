[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo      = "ee-in-a-box/altium-copilot"
$apiUrl    = "https://api.github.com/repos/$repo/releases/latest"
$installDir = "$env:LOCALAPPDATA\altium-copilot"
$exeDest   = "$installDir\altium-copilot.exe"
$statePath = "$env:USERPROFILE\.ee-in-a-box\altium-copilot-state.json"

# Logging helpers
function Write-Ok   { param($m) Write-Host "[OK] "    -ForegroundColor Green  -NoNewline; Write-Host $m }
function Write-Warn { param($m) Write-Host "[WARN] "  -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Write-Err  { param($m) Write-Host "[ERROR] " -ForegroundColor Red    -NoNewline; Write-Host $m }

$client = New-Object System.Net.WebClient

# --- Close Claude Desktop so MCP processes die cleanly and can be reopened fresh ---
# Filter to WindowsApps path to avoid matching Claude Code (VS Code extension)
$claudeProcs = Get-Process -Name "claude" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*WindowsApps*Claude*" }
$claudePkg = Get-AppxPackage -Name "Claude" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($claudeProcs) {
    Write-Warn "Claude Desktop will be closed and reopened automatically after install."
    Write-Host "Press Enter to continue, or Ctrl+C to cancel."
    Read-Host | Out-Null
    $claudeProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 1000
}

# --- Kill any running altium-copilot processes so the exe is not locked ---
Get-Process -Name "altium-copilot" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

New-Item -ItemType Directory -Force -Path $installDir | Out-Null

# --- Fetch latest release info ---
Write-Ok "Checking latest release..."
try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "altium-copilot-installer" }
    $version = $release.tag_name -replace '^v', ''
    $exeUrl  = "https://github.com/$repo/releases/latest/download/altium-copilot.exe"
} catch {
    Write-Err "Failed to fetch release info: $_"
    exit 1
}

Write-Ok "Latest version: $version"

# --- Download exe (overwrites existing) ---
$action = if (Test-Path $exeDest) { "Updating" } else { "Downloading" }
Write-Ok "${action} altium-copilot.exe..."
try {
    $client.DownloadFile($exeUrl, $exeDest)
} catch {
    Write-Err "Download failed: $_"
    exit 1
}
if (!(Test-Path $exeDest)) {
    Write-Host ""
    Write-Warn "WARNING: Download succeeded but altium-copilot.exe is missing."
    Write-Host "Your antivirus likely quarantined it. To fix:"
    Write-Host "  1. Open Windows Security > Virus & threat protection > Protection history"
    Write-Host "  2. Restore the file, or add $installDir to Defender exclusions."
    Write-Host ""
    exit 1
}

Write-Ok "Installed to: $exeDest"

# --- Add to PATH ---
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*altium-copilot*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$installDir", "User")
    $env:PATH = "$env:PATH;$installDir"
    Write-Ok "Added $installDir to PATH."
}

# --- Register with Claude Desktop ---
$msixPkg = Get-ChildItem "$env:LOCALAPPDATA\Packages\Claude_*" -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
$msixConfig    = if ($msixPkg) { "$($msixPkg.FullName)\LocalCache\Roaming\Claude\claude_desktop_config.json" } else { $null }
$roamingConfig = "$env:APPDATA\Claude\claude_desktop_config.json"

$configPath = if ($msixConfig -and (Test-Path $msixConfig)) { $msixConfig }
              elseif (Test-Path $roamingConfig)              { $roamingConfig }
              else                                           { $null }

if ($configPath) {
    $config = if (Test-Path $configPath) {
        Get-Content $configPath -Raw | ConvertFrom-Json
    } else {
        [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
    }
    if (-not $config.mcpServers) {
        $config | Add-Member -MemberType NoteProperty -Name mcpServers -Value ([PSCustomObject]@{})
    }
    $entry = [PSCustomObject]@{ command = $exeDest; args = @() }
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name "altium-copilot" -Value $entry -Force
    New-Item -ItemType Directory -Force -Path (Split-Path $configPath) | Out-Null
    $json = $config | ConvertTo-Json -Depth 10 -Compress
    [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding $false))
    Write-Ok "Registered with Claude Desktop. Restart Claude Desktop to apply."
} else {
    Write-Host ""
    Write-Warn "Claude Desktop not found."
    Write-Host "Install it from https://claude.ai/download then re-run this script to register."
    Write-Host ""
}

# --- Warn about conflicting .mcpb extension installation ---
$mcpbExtension = Get-ChildItem "$env:APPDATA\Claude\extensions\altium-copilot*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($mcpbExtension) {
    Write-Host ""
    Write-Warn "WARNING: A previous installation via the Claude Extensions UI was detected."
    Write-Host "Having both the extension and a direct config entry will run two copies"
    Write-Host "of Altium Copilot simultaneously."
    Write-Host "Fix: Open Claude Desktop > Extensions, uninstall Altium Copilot, then"
    Write-Host "restart Claude Desktop."
    Write-Host ""
}

# --- Register with Claude Code ---
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Ok "Registering with Claude Code..."
    claude mcp add --scope user altium-copilot -- altium-copilot
    Write-Ok "Done. Altium Copilot is ready in Claude Code."
} else {
    Write-Warn "Claude Code not found — skipping MCP registration."
}

# --- Write state file ---
New-Item -ItemType Directory -Force -Path (Split-Path $statePath) | Out-Null
$state = if (Test-Path $statePath) {
    Get-Content $statePath -Raw | ConvertFrom-Json
} else {
    [PSCustomObject]@{}
}
$state | Add-Member -MemberType NoteProperty -Name installed_version -Value $version -Force
$state | ConvertTo-Json -Depth 5 | Set-Content $statePath -Encoding UTF8

Write-Host ""
Write-Ok "Altium Copilot $version installed successfully."

# --- Reopen Claude Desktop if we closed it ---
if ($claudeProcs -and $claudePkg) {
    Write-Ok "Reopening Claude Desktop..."
    $manifest = Get-AppxPackageManifest $claudePkg
    $appId = $manifest.Package.Applications.Application.Id
    Start-Process "shell:AppsFolder\$($claudePkg.PackageFamilyName)!$appId"
}
