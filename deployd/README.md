# vw-deployd (GitHub Webhook Deploy Trigger)

Minimal deploy trigger designed for VaultWares infrastructure:

- Receives **GitHub Webhooks** (push events)
- Verifies `X-Hub-Signature-256` HMAC signature
- Runs a configured deploy command per repo
- Writes append-only logs

This intentionally avoids:
- GitHub-hosted runners running privileged workloads
- SSH from GitHub into servers
- Tailscale ephemeral nodes (Tailnet Lock friendly)

## Quick start (VPS)

1) Copy `config.example.yml` to `config.yml` and edit targets.
2) Export secrets via an env file:

```bash
export VW_GITHUB_WEBHOOK_SECRET='...'
export VW_DEPLOYD_CONFIG='/etc/vw-deployd/config.yml'
export VW_DEPLOYD_BIND='127.0.0.1:9033'
export VW_DEPLOYD_LOG='/var/log/vw-deployd.log'
```

3) Run:

```bash
python3 /opt/automation-suite/deployd/vw_deployd.py
```

4) Put Nginx in front and terminate TLS (recommended):
- Proxy `https://hooks.vaultwares.ca/github` → `http://127.0.0.1:9033/github`

5) Optional: systemd

- Create a dedicated user:

```bash
sudo useradd -m -s /usr/sbin/nologin vwdeploy || true
```

- Install the service file:

```bash
sudo mkdir -p /etc/vw-deployd
sudo cp /opt/automation-suite/deployd/vw-deployd.service /etc/systemd/system/vw-deployd.service
sudo systemctl daemon-reload
sudo systemctl enable --now vw-deployd
sudo systemctl status vw-deployd --no-pager
```

## Notes

- Signature verification requires the **raw request body**. Do not pre-parse or
  re-encode before validating.
- Deploy commands should be **idempotent** and safe to run multiple times.
