# automation-suite

Stealth browser automation toolkit with multi-provider support (Patchright, Kameleo, MultiLogin), proxy rotation, human-like interaction simulation, anti-bot detection, BFS crawling, and structured trace recording.

## Requirements

- Python 3.10+
- Windows (uses `APPDATA` for Firefox profile discovery, PowerShell paths)
- [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (anti-detection Playwright fork)

## Installation

```powershell
# Clone the repo
git clone https://github.com/p-potvin/automation-suite.git
cd automation-suite

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install -r requirements.txt

# Install Patchright browser binaries
patchright install chromium

# Copy environment template and fill in your values
cp .env.example .env
# Edit .env with your API keys, proxy URLs, and target domains
```

## Configuration

### `.env` file

All runtime configuration is driven by environment variables. Copy `.env.example` to `.env` and fill in your values:

| Variable | Description | Default |
|---|---|---|
| `STEALTH_PROVIDER` | Browser provider: `patchright`, `kameleo`, or `multilogin` | `patchright` |
| `STEALTH_HEADLESS` | Run browser headless (`true`/`false`) | `false` |
| `PROXY_URL` | Proxy URL for Tor/wireproxy (e.g. `socks5://127.0.0.1:9050`) | — |
| `IPOASIS_API_KEY` | IPoasis residential proxy API key | — |
| `IPOASIS_COUNTRY` | IPoasis proxy country code | `US` |
| `MULTILOGIN_API_URL` | MultiLogin API base URL | `https://api.multilogin.com/v1` |
| `MULTILOGIN_API_KEY` | MultiLogin API key | — |
| `KAMELEO_API_URL` | Kameleo local API URL | `http://localhost:5050` |
| `KAMELEO_PROFILE_ID` | Kameleo profile ID to launch | — |
| `CRAWL_ENABLED` | Enable BFS crawl after main flow | `false` |
| `CRAWL_MAX_DEPTH` | Max crawl depth | `2` |
| `CRAWL_MAX_PAGES` | Max pages to visit during crawl | `20` |
| `QA_MOUSE_PATHS_ENABLED` | Enable natural mouse path replay | `1` |
| `QA_MOUSE_PATHS_FILE` | Path to recorded mouse paths JSON | `test-results/natural-mouse-paths.json` |
| `REDTEAM_DRY_RUN` | Dry-run mode (no network requests) | `1` |
| `REDTEAM_ALLOWED_DOMAINS` | Comma-separated allowlist of target domains | `localhost,127.0.0.1` |
| `FLARESOLVERR_URL` | FlareSolverr endpoint for Cloudflare bypass | — |
| `VPN_ROTATE_COMMAND` | Command to rotate VPN IP | — |

### `config/settings.yaml`

YAML config for target URLs and form selectors. Environment variables override YAML values.

```yaml
targets:
  - url: "https://example.com"
    username_selector: "input[name='login']"
    password_selector: "input[name='password']"
    submit_selector: "input[type='submit']"
```

## Pipelines

### 1. Main Automation Flow (`main.py`)

The primary pipeline. Launches a stealth browser, navigates to the target URL, handles cookie overlays and age gates, simulates human behavior, fills and submits forms, checks for anti-bot blocks, extracts cookies, and optionally crawls the site.

```powershell
# Basic run (uses .env + config/settings.yaml)
python main.py

# With crawling enabled
$env:CRAWL_ENABLED = "true"
$env:CRAWL_MAX_DEPTH = "3"
python main.py

# With MultiLogin provider
$env:STEALTH_PROVIDER = "multilogin"
python main.py

# With Kameleo provider
$env:STEALTH_PROVIDER = "kameleo"
$env:KAMELEO_PROFILE_ID = "your-profile-id"
python main.py
```

**Flow steps:**
1. Load config from `settings.yaml` and `.env`
2. Resolve proxy (PROXY_URL → IPoasis → direct)
3. Launch stealth browser via configured provider
4. Navigate to target URL
5. Handle cookie overlays (`#ch2-dialog`) and age gates
6. Simulate human behavior (mouse paths, scrolling, delays)
7. Fill and submit form with human-like typing
8. Check for anti-bot blocks (CAPTCHA, challenge pages)
9. Extract and save cookies to `cookies/session.json`
10. Optional: BFS crawl with link extraction
11. Save metrics artifact to `test-results/artifacts/`
12. Write JSONL trace to `logs/`

### 2. Deployment Daemon (`deployd/vw_deployd.py`)

GitHub webhook receiver that triggers deploy scripts on push events. Runs as a systemd service.

```powershell
# Run directly (for testing)
python deployd/vw_deployd.py

# As a systemd service (Linux VPS)
sudo systemctl start vw-deployd
sudo systemctl enable vw-deployd
```

**Config:** `deployd/config.example.yml` — maps GitHub repos to deploy commands, restricts allowed owners, optional error notifications.

**Setup:** See `deployd/README.md` for full installation instructions including nginx reverse proxy and systemd service configuration.

## Modules

### Core Modules

| Module | Description |
|---|---|
| `main.py` | Main automation pipeline — orchestrates all modules |
| `stealth_browser.py` | Multi-provider browser launcher (Patchright/Kameleo/MultiLogin) with stealth init scripts |
| `browser_controller.py` | CDP browser connection and cookie extraction |
| `humanizer.py` | Human-like interaction: natural mouse path replay, typing, clicking, scrolling |
| `proxy_rotation.py` | Proxy resolution: Tor/wireproxy, IPoasis residential, URL parsing, redaction |
| `page_actions.py` | Page interaction: cookie overlays, age gates, ad tab recovery, BFS crawl, block detection |
| `trace_recorder.py` | Structured JSONL trace recording and anti-bot metrics artifact saving |
| `firefox_profile.py` | Firefox profile auto-discovery and cloning for Firefox automation |
| `multilogin_client.py` | MultiLogin API client (create/launch/cookies/close) |

### Deploy Daemon

| Module | Description |
|---|---|
| `deployd/vw_deployd.py` | GitHub webhook server with HMAC signature verification |
| `deployd/config.example.yml` | Deploy target mapping config |
| `deployd/vw-deployd.service` | systemd service file |
| `deployd/nginx-snippet.conf` | nginx reverse proxy config |

## Output Artifacts

| Path | Description |
|---|---|
| `cookies/session.json` | Extracted browser cookies after automation flow |
| `logs/trace_*.jsonl` | Structured trace events (one JSON per line) |
| `test-results/artifacts/run_*.json` | Anti-bot metrics: block status, visited endpoints, timing |

## Proxy Priority

1. **`PROXY_URL` env var** — Tor/wireproxy SOCKS5 or HTTP proxy (highest priority)
2. **IPoasis residential** — Rotating residential proxies via IPoasis API (if `IPOASIS_API_KEY` is set)
3. **Direct connection** — No proxy (fallback, logs a warning)

## Browser Provider Selection

Set `STEALTH_PROVIDER` in `.env`:

- **`patchright`** (default) — Anti-detection Chromium via Patchright with stealth init scripts. Uses persistent profile directory at `browser_profile/`.
- **`kameleo`** — Connects to a running Kameleo local API instance. Requires `KAMELEO_PROFILE_ID`.
- **`multilogin`** — Creates and launches a MultiLogin profile via API. Requires `MULTILOGIN_API_KEY`.

## License

See [LICENSE](LICENSE) for details.
