# PyInstaller spec for Isocline Desktop. Build from the repo root with:
#     pyinstaller packaging/desktop/isocline.spec --noconfirm
# Prerequisite: the static UI at apps/web/out (cd apps/web && npm run build:desktop).
# Output: dist/Isocline/ (Isocline.exe + _internal/). The installer (installer.iss) packages that folder.
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]  # repo root
API = ROOT / "apps" / "api"
UI = ROOT / "apps" / "web" / "out"
HERE = ROOT / "packaging" / "desktop"
SEARCH = ROOT / "apps" / "desktop-search"
if not (UI / "index.html").is_file():
    raise SystemExit(f"Static UI not found at {UI}. Run `npm run build:desktop` in apps/web first.")
# collect_submodules imports the package to list its modules, so it must be importable at spec time.
sys.path.insert(0, str(API))
os.environ.setdefault("PYTHONPATH", str(API))
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (API / "isocline" / "__init__.py").read_text()).group(1)

datas = [
    (str(API / "alembic"), "alembic"),  # migrations, run on every start (isocline.desktop.bootstrap)
    (str(UI), "web"),                   # exported Next.js UI, served by isocline.desktop.ui
    (str(SEARCH / "settings.template.yml"), "."),  # local search settings, copied to the data folder on first start
    (str(SEARCH / "LICENSE-NOTICE.txt"), "."),
]
# Sandbox runtime for Python steps (built by build.ps1); without it, Python steps report that they are unavailable.
RUNTIME = ROOT / "build" / "python-runtime"
if (RUNTIME / "python.exe").is_file():
    datas.append((str(RUNTIME), "python-runtime"))
else:
    print(f"WARNING: no sandbox runtime at {RUNTIME}; building without Python steps.")
# Packages that look themselves up by distribution metadata at runtime.
for dist in ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-instrumentation", "opentelemetry-instrumentation-fastapi",
             "email-validator", "fastapi", "pydantic", "uvicorn", "starlette"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

isocline_modules = collect_submodules("isocline", filter=lambda m: not m.startswith("isocline.worker"))
if len(isocline_modules) < 20:
    raise SystemExit(f"Only {len(isocline_modules)} isocline modules found; is apps/api importable?")
hiddenimports = (
    isocline_modules
    # uvicorn picks its loop/protocol/lifespan implementations by name at runtime.
    + collect_submodules("uvicorn")
    + collect_submodules("opentelemetry")
    + ["aiosqlite", "sqlalchemy.dialects.sqlite.aiosqlite"]
)

# Server-only or unused dependencies; keeping them out keeps the download small.
excludes = ["celery", "kombu", "billiard", "redis", "asyncpg", "psycopg", "psycopg2", "pgvector", "numpy", "pandas",
            "tkinter", "_tkinter", "matplotlib", "IPython", "pytest", "isocline.worker",
            "PIL", "yaml", "playwright", "greenlet.tests",
            "searx", "lxml", "babel", "flask", "curl_cffi"]  # these belong to IsoclineSearch.exe only  # not used by the app (pulled in only if installed)

a = Analysis(
    [str(HERE / "isocline_desktop.py")],
    pathex=[str(API)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

version_file = None
if os.name == "nt":
    nums = [int(x) for x in re.findall(r"\d+", VERSION)[:3]] + [0]
    while len(nums) < 4:
        nums.append(0)
    version_file = str(HERE / "build-version.txt")
    Path(version_file).write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Isocline'),
    StringStruct('FileDescription', 'Isocline Desktop'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('ProductName', 'Isocline'),
    StringStruct('ProductVersion', '{VERSION}'),
    StringStruct('OriginalFilename', 'Isocline.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)""", encoding="utf-8")

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Isocline",
    console=False,          # windowed app: no terminal window (logs go to %LOCALAPPDATA%\Isocline\logs)
    icon=str(HERE / "isocline.ico"),
    version=version_file,
    upx=False,              # UPX-packed executables trigger antivirus false positives
)
# ---------------------------------------------------------------------------------------------------------------
# IsoclineSearch.exe: local web search (SearXNG, AGPL-3.0-or-later). A separate program in the same folder; Isocline
# starts it and talks to it over HTTP on 127.0.0.1 (isocline.desktop.search). Shares _internal/ with Isocline.exe.
try:
    import searx  # noqa: F401
    HAVE_SEARCH = True
except ImportError:
    HAVE_SEARCH = False
    print("WARNING: SearXNG is not installed; building without local web search (Tavily/Brave keys still work).")

executables = [exe, a.binaries, a.datas]
if HAVE_SEARCH:
    search_a = Analysis(
        [str(SEARCH / "isocline_search.py")],
        # Engines are loaded by name at runtime. SearXNG validates that its static/templates folders exist and lists
        # its translations at import, so all package data is kept even though the search web UI is never served.
        datas=collect_data_files("searx"),
        hiddenimports=collect_submodules("searx", filter=lambda m: not m.startswith(("searx.webapp", "searx.webutils"))),
        excludes=["tkinter", "_tkinter", "numpy", "pandas", "matplotlib", "pytest", "isocline", "valkey", "PIL"],
        # SearXNG discovers its answerers, plugins and engines by listing its own package folders, so its modules
        # must exist as files on disk rather than inside the PYZ archive.
        module_collection_mode={"searx": "py"},
        noarchive=False,
    )
    search_pyz = PYZ(search_a.pure)
    search_exe = EXE(
        search_pyz, search_a.scripts, [],
        exclude_binaries=True,
        name="IsoclineSearch",
        # A console program, started by Isocline with CREATE_NO_WINDOW (no window appears): console programs always
        # get the stdin pipe that makes the search service exit together with the app.
        console=True,
        icon=str(HERE / "isocline.ico"),
        upx=False,
    )
    executables += [search_exe, search_a.binaries, search_a.datas]

coll = COLLECT(*executables, name="Isocline", upx=False)
