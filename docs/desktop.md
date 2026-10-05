# Isocline Desktop

Isocline Desktop runs the whole stack in one process for a single user on their own computer:
SQLite instead of PostgreSQL, in-process workers and scheduler instead of Redis + Celery, and the
web UI served by the API. Durability is unchanged: all state is in the database, so closing the
app (or a crash) mid-run loses nothing; interrupted runs resume on the next start.

## Run from source

Build the web UI as static files once (and after UI changes):

```bash
cd apps/web
npm ci
npm run build:desktop                   # writes apps/web/out (about 3 MB)
```

Then start the app; it finds `apps/web/out` automatically:

```bash
cd apps/api
pip install -r requirements-desktop.txt
python -m isocline.desktop              # native window
python -m isocline.desktop --browser    # default browser instead
python -m isocline.desktop --headless   # server only
```

Options: `--port N` (default 47321), `--data-dir PATH`, `--debug`.

## Build the Windows installer

On a Windows machine with Node.js 18+, Python 3.11+ and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\desktop\build.ps1
```

This builds the UI, installs the pinned SearXNG version (`$SEARXNG_REF` in the script; bump it for each release,
since search engines change their pages often), bundles everything with PyInstaller into `dist\Isocline\` (a portable folder with
`Isocline.exe`), starts it once as a smoke test, and writes `dist\installer\Isocline-Setup-<version>.exe`.
Add `-SkipInstaller` to stop after the portable folder, or `-SandboxOnly` to build the Python sandbox runtime and
run its isolation tests only.

The installer installs per user without an administrator prompt, adds a Start menu entry (and optionally a
desktop icon), and keeps user data on upgrade and uninstall.

**Automatic builds:** `.github/workflows/desktop.yml` runs the same script on GitHub's Windows runners. Publishing
a GitHub Release attaches the installer to it; you can also run the workflow by hand from the Actions tab.

**Unsigned builds:** until the executable is code-signed, Windows SmartScreen shows "Windows protected your PC"
on first launch (users click **More info → Run anyway**). Free signing for open-source projects is available
through the SignPath Foundation.

## Where data lives

| OS      | Folder                                      |
| ------- | ------------------------------------------- |
| Windows | `%LOCALAPPDATA%\Isocline`                   |
| macOS   | `~/Library/Application Support/Isocline`    |
| Linux   | `$XDG_DATA_HOME/isocline`                   |

Running from source (`python -m isocline.desktop`) uses a separate `Isocline-dev` folder next to it, so test
accounts, keys and projects from development never appear in the installed app.

The data folder contains `isocline.db`, `uploads/`, `secrets.env` (generated on first start; back it up with the
database, since stored credentials can't be decrypted without it) and `logs/isocline.log`.

Model keys can be added in the UI (**Keys & secrets**) or in `isocline.env` in the same folder,
for example `OPENAI_API_KEY=...`.

## Page URLs

Pages that show one record use a query parameter, for example `/runs/view?id=<id>`, so the UI can be a static
export. Build these links with `routes` from `apps/web/src/lib/routes.tsx`. Old `/runs/<id>`-style links redirect
in both the server build and the desktop app.

## Differences from the server stack

- **Python steps:** run on Windows in an AppContainer sandbox (the isolation Edge and Chrome use) inside a Job
  Object, with the bundled Python runtime (numpy, pandas, scipy, matplotlib, as on the server). Windows enforces:
  no access to the user's files or Isocline's data (only a private, per-run folder), no network (including
  localhost), no child processes, limits on memory, CPU and wall time, and the process dies with Isocline.
  `build.ps1` runs escape tests (`packaging/desktop/tests`) against every build and stops if any attempt succeeds;
  `.github/workflows/desktop-sandbox.yml` runs them on GitHub's Windows machines when the sandbox changes.
  Not a virtual machine: a Windows kernel vulnerability could in principle break out, as with any OS sandbox.
- **Web search:** works without any key. The installer includes `IsoclineSearch.exe`, a local SearXNG service that
  Isocline starts in the background (log: `logs\search.log`, settings: `searxng\settings.yml` in the data folder).
  If a Tavily or Brave key is configured, it is used instead. IsoclineSearch is AGPL-3.0 (SearXNG's license) and runs
  as a separate program; see `apps/desktop-search/LICENSE-NOTICE.txt`. `build.ps1 -SkipSearch` builds without it.
- **Knowledge retrieval:** similarity is computed in Python instead of a pgvector index; fine for personal-sized knowledge bases.
- **Ollama:** defaults to `http://127.0.0.1:11434`.
- One app instance per data folder; launching it again shows the running instance.

The server stack (`docker compose up`) is unaffected by any of this.
