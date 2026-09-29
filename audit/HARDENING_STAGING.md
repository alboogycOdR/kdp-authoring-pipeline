# Staging hardening checklist (clawsrv, Tailscale, Caddy, systemd --user)

Scope: configuration-as-documentation from `docs/operations/ENVIRONMENTS.md`. The unit files, Caddyfile and `kdp-staging` wrapper are **not in the repository** — the first action is to commit sanitised templates so the deployment is reviewable and reproducible.

## 1. Who is trusted today, and with what
Any device the tailnet ACL lets reach `100.78.70.2:8767` can: read every manuscript and plan; create books and titles; run paid generation up to limits it can itself raise to $10,000/month per project; accept assets, decide canon/verification/rights, record every release checklist item and approve releases — under any name (AUD-001). If a tailnet device is compromised (or a browser on it visits a hostile page and the proxy forwards foreign Host/Origin, AUD-002), all of that is available to the attacker.

## 2. Access
- [ ] Tailscale ACL: allow only the owner's tagged devices to `tag:kdp-staging:8767`; deny all else; no `autogroup:member` wildcard.
- [ ] Authenticate at Caddy: either Tailscale identity (`tailscale serve`/`Tailscale-User-Login` header from a trusted local proxy) or `basic_auth` with bcrypt hashes / forward_auth. Strip any client-supplied identity header before setting it.
- [ ] App: accept identity only from the proxy (bind 127.0.0.1, verify `REMOTE_ADDR`), map to operator, drop form name fields (ADR-0003).
- [ ] Caddy site address = exact `100.78.70.2:8767`; respond 421 to other Hosts; reject requests whose `Origin` is not `http://100.78.70.2:8767`; do not blindly strip Origin.
- [ ] Rate/connection limits at Caddy (e.g. `max_conns`), request body limit 256 KB.
- [ ] Consider HTTPS via `tailscale cert` so forms and identity are not sent in cleartext across the tailnet.

## 3. systemd --user units
- [ ] `Restart=on-failure`, `RestartSec=5`.
- [ ] `MemoryMax=512M`, `TasksMax=128` (bounds thread-per-connection growth, AUD-018).
- [ ] `ProtectSystem=strict`, `ProtectHome=read-only` + `ReadWritePaths=/home/clawusr/apps/kdp-authoring-pipeline/.kdp /home/clawusr/apps/kdp-authoring-pipeline/projects`, `PrivateTmp=yes`, `NoNewPrivileges=yes`, `UMask=0077` (user units support a subset — verify each with `systemd-analyze --user security`).
- [ ] Logs to journald (patched access log), `journalctl --user -u kdp-workspace` retention set.

## 4. Secrets
- [ ] Key file `600`, dir `700` (documented) — verify in a deploy check script.
- [ ] The wrapper exports the key into the service environment; it is readable via `/proc/<pid>/environ` by the same user. Accept (documented) or run the app under a dedicated user with no shell.
- [ ] Env of the service must contain **only** the provider key — no cloud/VCS tokens (AUD-009); set `KDP_PROVIDER_HOST_ALLOWLIST=api.openai.com` explicitly.
- [ ] Unset `HTTP(S)_PROXY` in the unit unless required (httpx honours them; `trust_env=True`).
- [ ] Rotation runbook: write new key → `systemctl --user restart kdp-workspace` → `kdp providers check … --connect` once → revoke old key at provider. Revocation: revoke at provider first.
- [ ] Provider-side spend limit configured in the provider dashboard (independent of app budgets).

## 5. Data protection and backups
- [ ] Nightly paired backup: `sqlite3 .kdp/state.db ".backup state.bak"` (or Python `Connection.backup`) + `tar` of `projects/` + `sha256sum` manifest; weekly restore test into a scratch path using `kdp relocate --from` (patched) and `kdp doctor` → expect zero FAIL. Measured RPO = 24 h, RTO = minutes for current sizes.
- [ ] Encrypt backups at rest; they contain unpublished manuscripts and operator names (POPIA personal information).

## 6. Observability
- [ ] Path-only access log (patch AUD-034) + audit events + a daily `kdp budget show` per project posted to the owner; alert when ≥ warning %.
- [ ] `/readyz` that checks DB and disk (AUD-033); monitor it rather than `/healthz`.

## 7. Deployment
- [ ] Deploy script: `git fetch --tags && git checkout <tag> && pip install -e . && kdp db status && backup && restart && smoke test (/readyz, doctor)`; record deployed tag in a file the Workspace footer shows (resolves the staging-version ambiguity in AUD-039).
- [ ] Rollback = restore the pre-deploy backup + previous tag (schema version prevents older code on newer DB once patched).
- [ ] Drift: staging and dev DBs diverge by design — show the environment name prominently in the Workspace header; never copy DBs without `relocate` + `doctor`.
