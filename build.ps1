<#
.SYNOPSIS
    Builds TeslaCam Viewer into a standalone Windows executable.

.DESCRIPTION
    1. Converts resources/icon.png -> resources/icon.ico (needs Pillow)
    2. Runs PyInstaller with TeslaCamViewer.spec
    3. Prints the output path on success

.EXAMPLE
    .\build.ps1
    .\build.ps1 -Clean   # delete build/ and dist/ first
#>

param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  TeslaCam Viewer — Windows Build" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 0. Optional clean ────────────────────────────────────────────────────────
if ($Clean) {
    Write-Host "Cleaning previous build artefacts..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "$Root\build"  -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$Root\dist"   -ErrorAction SilentlyContinue
    Write-Host "  Done." -ForegroundColor Green
}

# ── 1. Convert PNG icon -> ICO ────────────────────────────────────────────────
$iconPng = "$Root\resources\icon.png"
$iconIco = "$Root\resources\icon.ico"

if (-not (Test-Path $iconPng)) {
    Write-Error "Icon not found: $iconPng"
    exit 1
}

Write-Host "Converting icon.png -> icon.ico..." -ForegroundColor Yellow
python -c @"
from PIL import Image
img = Image.open(r'$iconPng').convert('RGBA')
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
imgs[0].save(r'$iconIco', format='ICO', sizes=sizes, append_images=imgs[1:])
print('  icon.ico written.')
"@

# ── 2. Run PyInstaller ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Running PyInstaller..." -ForegroundColor Yellow
python -m PyInstaller "$Root\TeslaCamViewer.spec" --noconfirm

# ── 3. Done ──────────────────────────────────────────────────────────────────
$outDir = "$Root\dist\TeslaCamViewer"
if (Test-Path "$outDir\TeslaCamViewer.exe") {
    Write-Host ""
    Write-Host "  Build successful!" -ForegroundColor Green
    Write-Host "  Output: $outDir" -ForegroundColor Green

    # ── LGPL compliance reminder ─────────────────────────────────────────────
    $missing = @()
    if (-not (Test-Path "$Root\LICENSES\LGPL-2.1.txt")) { $missing += "LGPL-2.1.txt  (FFmpeg)" }
    if (-not (Test-Path "$Root\LICENSES\LGPL-3.0.txt")) { $missing += "LGPL-3.0.txt  (Qt / PySide6)" }
    if (-not (Test-Path "$Root\LICENSES\Apache-2.0.txt")) { $missing += "Apache-2.0.txt (OpenSSL)" }

    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "  ⚠  LGPL compliance: add these license texts to LICENSES/ before distributing:" -ForegroundColor Yellow
        foreach ($f in $missing) { Write-Host "       • $f" -ForegroundColor Yellow }
        Write-Host "     Texts: https://www.gnu.org/licenses/" -ForegroundColor Yellow
    }
    Write-Host ""
} else {
    Write-Error "Build failed — TeslaCamViewer.exe not found in $outDir"
    exit 1
}
