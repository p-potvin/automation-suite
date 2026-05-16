# vw-deployd (GitHub Webhook Deploy Trigger)

`vw-deployd` is a small, conservative webhook receiver that lets **your VPS**
pull and deploy repositories **after** a signed GitHub `push` event.

It is designed for VaultWares infra constraints:

- **Tailnet Lock friendly** (no ephemeral tailnet nodes required)
- Works with **public SSH closed** (no SSH from GitHub)
- Minimizes GitHub trust: GitHub only delivers an event; the VPS does the work

## What it does

- Exposes:
  - `GET /health` → health response
  - `POST /github` → GitHub webhook receiver
- Verifies HMAC signature:
  - `X-Hub-Signature-256` (SHA-256) against `VW_GITHUB_WEBHOOK_SECRET`
- Accepts only:
  - `X-GitHub-Event: push` (ignores other events)
  - configured repos + configured branch (defaults to `main`)
- Runs a configured **deploy command** per repo, with a small environment payload.
- Appends to a log file (append-only) for auditability.

## What it intentionally does not do

- No “execute workflow steps” on the server (unlike self-hosted runners).
- No automatic secret syncing.
- No multi-stage orchestration (use a real deploy tool later if needed).

## Why this instead of self-hosted GitHub runners

Self-hosted runners are powerful but risky: a compromised repo/workflow can run
arbitrary code on your server. `vw-deployd` restricts that blast radius to a
single code path:

1) verify signature
2) check repo + branch allowlist
3) run a pre-approved command

## Security model (quick)

- Trust boundary is the webhook secret:
  - If `VW_GITHUB_WEBHOOK_SECRET` is leaked, an attacker can trigger deploy
    commands.
- Deploy scripts must:
  - be idempotent
  - deploy by commit SHA (not “whatever main is right now”)
  - avoid interactive prompts
  - fail fast and leave the current deployment intact

## Install (Debian/Ubuntu VPS)

### 1) Dependencies

```bash
apt-get update
apt-get install -y nginx git python3 python3-yaml ca-certificates curl
```

### 2) Place code

Recommended location:

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/p-potvin/automation-suite.git automation-suite
```

### 3) Create a service user

```bash
useradd -m -s /usr/sbin/nologin vwdeploy || true
```

### 4) Configure environment + targets

Create directories:

```bash
mkdir -p /etc/vw-deployd /var/www/deploy-scripts /var/log
touch /var/log/vw-deployd.log
chown vwdeploy:vwdeploy /var/log/vw-deployd.log
chmod 640 /var/log/vw-deployd.log
```

Generate a webhook secret (save it for GitHub too):

```bash
openssl rand -hex 32
```

Create `/etc/vw-deployd/env` (do **not** commit this anywhere):

```bash
cat >/etc/vw-deployd/env <<'EOF'
VW_GITHUB_WEBHOOK_SECRET=REPLACE_ME
VW_DEPLOYD_CONFIG=/etc/vw-deployd/config.yml
VW_DEPLOYD_BIND=127.0.0.1:9033
VW_DEPLOYD_LOG=/var/log/vw-deployd.log
EOF

chmod 600 /etc/vw-deployd/env
chown root:root /etc/vw-deployd/env
```

Create `/etc/vw-deployd/config.yml` by starting from `config.example.yml`:

```bash
cp /opt/automation-suite/deployd/config.example.yml /etc/vw-deployd/config.yml
```

Edit `targets` to match your repos and deploy scripts.

## Deploy scripts

Each target runs a single command on the VPS, for example:

- `/var/www/deploy-scripts/deploy-vaultwares-docs.sh`

`vw-deployd` sets:

- `VW_REPO_FULL_NAME` (e.g., `p-potvin/vaultwares-docs`)
- `VW_REF` (e.g., `refs/heads/main`)
- `VW_AFTER` (commit SHA)
- `VW_DELIVERY` (GitHub delivery id)
- `VW_EVENT` (`push`)

Best practice for scripts:

- Deploy **by SHA**: `git fetch origin "$VW_AFTER"` then `git checkout -f "$VW_AFTER"`.
- Use an atomic swap:
  - build into `dist.new`
  - move current `dist` to `dist.prev`
  - rename `dist.new` to `dist`
- Use `flock` to prevent overlapping deploys per service.

## systemd

Install the unit file:

```bash
cp /opt/automation-suite/deployd/vw-deployd.service /etc/systemd/system/vw-deployd.service
systemctl daemon-reload
systemctl enable --now vw-deployd
systemctl status vw-deployd --no-pager
```

Health check:

```bash
curl -fsS http://127.0.0.1:9033/health
```

## Nginx

Terminate TLS at Nginx and proxy to the local service:

- Proxy `https://hooks.vaultwares.ca/github` → `http://127.0.0.1:9033/github`

Use the `nginx-snippet.conf` example as a starting point.

Important:
- Do not transform the webhook body before it reaches the app.
- Ensure GitHub sends `application/json`.

## GitHub configuration (per repository)

Repo → Settings → Webhooks → Add webhook:

- Payload URL: `https://hooks.vaultwares.ca/github`
- Content type: `application/json`
- Secret: same value as `VW_GITHUB_WEBHOOK_SECRET`
- Events: “Just the push event”

GitHub will send `ping` events; `vw-deployd` responds `pong`.

## Logging / troubleshooting

Tail the log:

```bash
tail -n 200 /var/log/vw-deployd.log
```

Common failures:

- `bad_signature`:
  - wrong secret in GitHub webhook vs `/etc/vw-deployd/env`
  - request not reaching the app unchanged
- `repo_not_configured`:
  - missing `targets["owner/repo"]` entry
- deploy exit `1`:
  - your deploy script failed (permissions, missing deps, merge conflicts, etc.)

## Hardening checklist

- Keep `VW_GITHUB_WEBHOOK_SECRET` only in `/etc/vw-deployd/env`.
- Keep the service bound to `127.0.0.1` and expose only via Nginx + TLS.
- Consider IP allowlisting GitHub webhook ranges at Nginx (optional).
- Keep deploy scripts in `/var/www/deploy-scripts` and owned by `root` or
  `vwdeploy`, but not world-writable.

## Roadmap ideas (later)

- richer notification integrations (Slack/email)
- per-target timeouts and health checks
- release retention policy + automatic rollback
