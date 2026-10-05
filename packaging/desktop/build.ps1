<#
  Builds the Isocline Desktop installer on Windows.

    powershell -ExecutionPolicy Bypass -File packaging\desktop\build.ps1

  Requires: Node.js 18+, Python 3.11+ (on PATH), Inno Setup 6 (https://jrsoftware.org/isinfo.php).
  Produces: dist\Isocline\Isocline.exe (portable folder) and dist\installer\Isocline-Setup-<version>.exe
  Use -SkipInstaller to stop after the portable folder (no Inno Setup needed).
  Use -SkipSearch to build without the bundled local web search (IsoclineSearch.exe, SearXNG).
  Use -SandboxOnly to build the Python sandbox runtime and run its isolation tests, then stop.
#>
param([switch]$SkipInstaller, [switch]$SkipUi, [switch]$SkipSearch, [switch]$SkipSandboxTests, [switch]$SandboxOnly)
# SearXNG version bundled as IsoclineSearch.exe (AGPL-3.0; source offer in apps/desktop-search/LICENSE-NOTICE.txt).
# Search engines change their pages often; bump this to a recent commit for each release.
$SEARXNG_REF = "d48c4b555421e824342c51d68482dd0898e54d0f"
# Python runtime for sandboxed Python steps: the official embeddable CPython plus the same data-science packages as the
# server sandbox image (workers/python-sandbox/runner.Dockerfile).
$SANDBOX_PYTHON = "3.12.10"
$SANDBOX_PACKAGES = @("numpy==2.1.*", "pandas==2.2.*", "scipy==1.14.*", "matplotlib==3.9.*")
$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $Root
$Version = (Select-String -Path apps\api\isocline\__init__.py -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "== Isocline Desktop $Version" -ForegroundColor Cyan

if ($SandboxOnly) { $SkipUi = $true; $SkipSearch = $true }
if (-not $SkipUi) {
  Write-Host "== 1/6 Building the web UI (static export)" -ForegroundColor Cyan
  Push-Location apps\web
  npm ci --no-audit --no-fund; if ($LASTEXITCODE) { throw "npm ci failed" }
  npm run build:desktop; if ($LASTEXITCODE) { throw "UI build failed" }
  Pop-Location
}

Write-Host "== 2/6 Preparing a clean Python environment" -ForegroundColor Cyan
# A dedicated venv keeps unrelated packages (e.g. from conda base) out of the bundle.
if (-not (Test-Path .venv-desktop)) { python -m venv .venv-desktop; if ($LASTEXITCODE) { throw "venv failed" } }
$Py = "$Root\.venv-desktop\Scripts\python.exe"
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -r apps\api\requirements-desktop.txt pyinstaller --quiet; if ($LASTEXITCODE) { throw "pip install failed" }

if (-not $SkipSearch) {
  Write-Host "   Installing SearXNG $($SEARXNG_REF.Substring(0, 8)) for local web search" -ForegroundColor Cyan
  # No git here: SearXNG's repository contains a file name that is invalid on Windows (a ':' in utils\templates),
  # and Git for Windows refuses to check out or even archive such a tree. Instead, download GitHub's zip of the pinned
  # commit and extract only the files the package needs.
  $Src = Join-Path $Root "build\searxng-src"
  $Zip = Join-Path $Root "build\searxng-$($SEARXNG_REF.Substring(0, 12)).zip"
  New-Item -ItemType Directory -Force (Join-Path $Root "build") | Out-Null
  $ProgressPreference = "SilentlyContinue"  # Windows PowerShell's progress bar makes downloads very slow
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  if (-not (Test-Path $Zip)) {
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/searxng/searxng/archive/$SEARXNG_REF.zip" -OutFile "$Zip.part"
    Move-Item -Force "$Zip.part" $Zip
  }
  if (Test-Path $Src) { Remove-Item -Recurse -Force $Src }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Keep = @("searx/", "setup.py", "README.rst", "requirements.txt", "requirements-dev.txt")
  $Archive = [IO.Compression.ZipFile]::OpenRead($Zip)
  try {
    $Prefix = $Archive.Entries[0].FullName.Split("/")[0] + "/"  # e.g. searxng-<commit>/
    foreach ($Entry in $Archive.Entries) {
      if (-not $Entry.FullName.StartsWith($Prefix) -or $Entry.FullName.EndsWith("/")) { continue }
      $Rel = $Entry.FullName.Substring($Prefix.Length)
      $Wanted = $false
      foreach ($k in $Keep) { if ($Rel -eq $k -or ($k.EndsWith("/") -and $Rel.StartsWith($k))) { $Wanted = $true; break } }
      if (-not $Wanted) { continue }
      $Dest = Join-Path $Src $Rel.Replace("/", [IO.Path]::DirectorySeparatorChar)
      New-Item -ItemType Directory -Force (Split-Path $Dest) | Out-Null
      [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Dest, $true)
    }
  } finally { $Archive.Dispose() }
  if (-not (Test-Path (Join-Path $Src "searx\__init__.py"))) { throw "searxng download looks incomplete" }
  # Record the version in the package (what `python -m searx.version freeze` writes), so the bundled copy does not
  # look for a git checkout at runtime. Format: <commit date as Y.M.D>+<9-character commit hash>. GitHub stamps every
  # file in the zip with the commit time, so the date comes from the archive itself (no extra network call).
  $Archive = [IO.Compression.ZipFile]::OpenRead($Zip)
  try { $Date = $Archive.Entries[0].LastWriteTime.ToString("yyyy.M.d", [Globalization.CultureInfo]::InvariantCulture) }
  catch { $Date = "0.0.0" }
  finally { $Archive.Dispose() }
  $V = "$Date+$($SEARXNG_REF.Substring(0, 9))"
  $Frozen = @"
# SPDX-License-Identifier: AGPL-3.0-or-later
# generated by Isocline packaging/desktop/build.ps1
VERSION_STRING = "$V"
VERSION_TAG = "$V"
DOCKER_TAG = "$($V.Replace('+', '-'))"
GIT_URL = "https://github.com/searxng/searxng"
GIT_BRANCH = "master"
"@
  [IO.File]::WriteAllText((Join-Path $Src "searx/version_frozen.py"), $Frozen, (New-Object Text.UTF8Encoding $false))
  & $Py -m pip install -r (Join-Path $Src "requirements.txt") --quiet; if ($LASTEXITCODE) { throw "searxng requirements failed" }
  & $Py -m pip install --no-build-isolation --no-deps $Src --quiet; if ($LASTEXITCODE) { throw "searxng install failed" }
} elseif (-not $SandboxOnly) {
  # -SkipSearch: make sure a SearXNG from an earlier build does not end up in the bundle. (No `2>$null` here: in
  # Windows PowerShell 5.1 a redirected warning from a native command becomes a fatal error under "Stop".)
  & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('searx') else 1)"
  if ($LASTEXITCODE -eq 0) { & $Py -m pip uninstall -y searxng --quiet }
}

Write-Host "== 3/6 Building the sandbox Python runtime" -ForegroundColor Cyan
$Rt = Join-Path $Root "build\python-runtime"
$SandboxSrc = Join-Path $Root "apps\api\isocline\desktop\sandbox\boot.py"
$HarnessSrc = Join-Path $Root "workers\python-sandbox\harness.py"
$Want = "$SANDBOX_PYTHON|$($SANDBOX_PACKAGES -join ' ')|$((Get-FileHash $SandboxSrc).Hash)|$((Get-FileHash $HarnessSrc).Hash)"
$Stamp = Join-Path $Rt ".isocline-runtime"
if ((Test-Path $Stamp) -and ((Get-Content $Stamp -Raw).Trim() -eq $Want)) {
  Write-Host "   up to date"
} else {
  if (Test-Path $Rt) { Remove-Item -Recurse -Force $Rt }
  New-Item -ItemType Directory -Force (Join-Path $Root "build") | Out-Null  # a fresh checkout has no build folder yet
  $ProgressPreference = "SilentlyContinue"
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $Embed = Join-Path $Root "build\python-$SANDBOX_PYTHON-embed-amd64.zip"
  if (-not (Test-Path $Embed)) {
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$SANDBOX_PYTHON/python-$SANDBOX_PYTHON-embed-amd64.zip" -OutFile "$Embed.part"
    Move-Item -Force "$Embed.part" $Embed
  }
  Expand-Archive -Path $Embed -DestinationPath $Rt
  $Tag = ($SANDBOX_PYTHON.Split(".")[0..1] -join "")  # 3.12.10 -> 312
  # Fixed import path: the standard library, the runtime folder and its own site-packages; nothing from the system.
  [IO.File]::WriteAllText((Join-Path $Rt "python$Tag._pth"), "python$Tag.zip`r`n.`r`nLib\site-packages`r`n", (New-Object Text.UTF8Encoding $false))
  $Site = Join-Path $Rt "Lib\site-packages"
  & $Py -m pip install --target $Site --platform win_amd64 --python-version $SANDBOX_PYTHON.Substring(0, 4) --implementation cp `
        --only-binary=:all: --no-compile --quiet @SANDBOX_PACKAGES
  if ($LASTEXITCODE) { throw "sandbox packages failed to install" }
  # Not needed at run time: test suites, console scripts, stray wheel files.
  Get-ChildItem $Site -Directory -Recurse -Filter tests | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force (Join-Path $Site "bin"), (Join-Path $Site "share") -ErrorAction SilentlyContinue
  Get-ChildItem $Site -Filter *.whl | Remove-Item -Force
  # pip installs into a temporary folder and moves the packages here. Since Python 3.13, temporary folders on Windows
  # get private permissions that block inheritance, and moved folders keep them, so the sandbox's read permission on
  # the runtime would not reach them. Reset everything to inherit from the runtime folder.
  icacls $Rt /reset /T /C /Q | Out-Null
  if ($LASTEXITCODE) { throw "could not reset permissions on the sandbox runtime" }
  Copy-Item $SandboxSrc (Join-Path $Rt "boot.py")
  Copy-Item $HarnessSrc (Join-Path $Rt "harness.py")
  # Precompile (the runtime is read-only inside the sandbox) and prebuild matplotlib's font cache (copied per run).
  & (Join-Path $Rt "python.exe") -m compileall -q -j 0 $Site | Out-Null
  $env:MPLCONFIGDIR = Join-Path $Rt "mplcache"
  & (Join-Path $Rt "python.exe") -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.font_manager"
  $rc = $LASTEXITCODE; Remove-Item Env:MPLCONFIGDIR
  if ($rc) { throw "sandbox runtime does not start" }
  [IO.File]::WriteAllText($Stamp, $Want)
}
$RtSize = "{0:N0} MB" -f ((Get-ChildItem $Rt -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "   OK: build\python-runtime ($RtSize)" -ForegroundColor Green

if (-not $SkipSandboxTests) {
  Write-Host "== 4/6 Sandbox isolation tests (escape attempts must all be blocked)" -ForegroundColor Cyan
  & $Py -m pip install pytest --quiet
  $env:ISOCLINE_SANDBOX_RUNTIME = $Rt
  & $Py -m pytest packaging\desktop\tests -q -p no:cacheprovider --tb=line
  $rc = $LASTEXITCODE
  if ($rc) {
    Write-Host "== Sandbox diagnostic (which protection breaks start-up?)" -ForegroundColor Yellow
    & $Py packaging\desktop\tests\diagnose_sandbox.py
  }
  Remove-Item Env:ISOCLINE_SANDBOX_RUNTIME
  if ($rc) { throw "Sandbox isolation tests failed: do not ship this build" }
} else {
  Write-Host "== 4/6 Sandbox isolation tests SKIPPED (-SkipSandboxTests)" -ForegroundColor Yellow
}
if ($SandboxOnly) { Write-Host "   Sandbox runtime built and verified." -ForegroundColor Green; return }

Write-Host "== 5/6 Bundling with PyInstaller" -ForegroundColor Cyan
& $Py -m PyInstaller packaging\desktop\isocline.spec --noconfirm --clean; if ($LASTEXITCODE) { throw "PyInstaller failed" }

Write-Host "   Smoke test" -ForegroundColor Cyan
$Data = Join-Path $env:TEMP "isocline-smoke-$([guid]::NewGuid())"
$Proc = Start-Process -FilePath dist\Isocline\Isocline.exe -ArgumentList "--headless","--port","47399","--data-dir",$Data -PassThru
$ok = $false
for ($i = 0; $i -lt 90 -and -not $ok; $i++) {
  Start-Sleep -Seconds 1
  try { $ok = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:47399/healthz -TimeoutSec 2).StatusCode -eq 200 } catch {}
}
$ui = $false
if ($ok) { try { $ui = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:47399/login -TimeoutSec 5).StatusCode -eq 200 } catch {} }
$search = $SkipSearch
if ($ok -and -not $SkipSearch) {
  # The search service starts in the background; it logs its port once it is listening.
  for ($i = 0; $i -lt 30 -and -not $search; $i++) {
    Start-Sleep -Seconds 1
    $search = [bool](Select-String -Path (Join-Path $Data "logs\search.log") -Pattern "listening on" -Quiet -ErrorAction SilentlyContinue)
  }
}
Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
if (-not ($ok -and $ui -and $search)) {
  Get-Content (Join-Path $Data "logs\search.log") -Tail 20 -ErrorAction SilentlyContinue
  Get-Content (Join-Path $Data "logs\isocline.log") -Tail 40 -ErrorAction SilentlyContinue
  throw "Smoke test failed (api=$ok ui=$ui search=$search)"
}
Remove-Item $Data -Recurse -Force -ErrorAction SilentlyContinue
$Size = "{0:N0} MB" -f ((Get-ChildItem dist\Isocline -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "   OK: dist\Isocline ($Size)" -ForegroundColor Green

if ($SkipInstaller) { return }
Write-Host "== 6/6 Building the installer (Inno Setup)" -ForegroundColor Cyan
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
  $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isinfo.php or run with -SkipInstaller." }
& $Iscc "/DAppVersion=$Version" packaging\desktop\installer.iss; if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-ChildItem dist\installer\*.exe | ForEach-Object { Write-Host ("   OK: {0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green }
