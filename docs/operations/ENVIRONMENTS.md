# Development and staging environments

This is the operational map for the current two-environment setup, recorded on 2026-09-29. It does not change the [architecture hierarchy](../../AGENTS.md) or authorize provider calls, approvals, or publication.

| Role | Location | Workspace access | Operational state |
| --- | --- | --- | --- |
| Development | `C:\Projects\kdp-authoring-pipeline` on the Windows development machine | `http://127.0.0.1:8765/` when started locally | Local `.kdp/state.db` and `projects/` contain the existing Pilot work, including Pilot 1B. |
| Staging | `clawsrv:/home/clawusr/apps/kdp-authoring-pipeline` | `http://100.78.70.2:8767/` over Tailscale | Separate `.kdp/state.db` and `projects/` now contain both existing projects, including Pilot 1B. |

The VPS checkout was installed from annotated tag `v1.0-platform-complete` (`7b5feb6`) with a Python 3.12 virtual environment. Development and staging have independent SQLite files and project artefacts. On 2026-09-29, a consistent SQLite backup and project archive were transferred to staging. An audited path rebase updated 77 references; 64 asset hashes, four build-manifest hashes, both title inspections, and foreign keys checked cleanly. There is no automatic synchronization or promotion after this one-time migration.

## VPS service and access

- `kdp-workspace.service` runs the staging app on VPS loopback `127.0.0.1:8766`.
- `kdp-workspace-tailnet.service` runs a user-owned Caddy proxy bound only to the VPS Tailscale IP, forwarding port `8767` to the loopback app. Its configuration is at `/home/clawusr/.config/kdp-workspace/Caddyfile`.
- These are enabled `systemd --user` services under `clawusr`; user lingering is enabled. Routine status checks do not require `sudo`.

The Workspace has **no application authentication**. Tailnet membership and ACLs are the access boundary; only trusted operators should be permitted to reach it. Do not expose the port on a public interface. The current Tailscale IP can be checked with `ssh clawsrv tailscale ip -4`; if it changes, update the proxy binding and this document together.

## Routine checks

From development, `ssh clawsrv` gives access to the VPS. For a read-only service check, run:

```bash
systemctl --user status kdp-workspace.service kdp-workspace-tailnet.service
curl --fail http://127.0.0.1:8766/healthz
```

The staging browser URL above should display the Workspace and both migrated titles. Use `/home/clawusr/.local/bin/kdp-staging doctor --root /home/clawusr/apps/kdp-authoring-pipeline` to inspect the staging checkout without making a provider connection. The `kdp-staging` wrapper supplies the provider key to CLI commands without displaying it; the Workspace service uses the same wrapper. The provider profile `openai-main-authoring-low` is selected for Pilot 1B, uses `gpt-5` with low reasoning, a 4,000 output-token default and a 180-second read timeout, and passes the offline configuration check.

The VPS key is in `/home/clawusr/.config/kdp-workspace/openai.key` (file mode `600`, directory mode `700`), outside the repository and SQLite. The Windows development user has `OPENAI_API_KEY` configured. A key rotation must update this OS file through a secret-safe channel and restart `kdp-workspace.service`. Never display the value or put it in project artefacts. Offline readiness confirms only that a value is present. One isolated, budget-capped real generation call on 2026-09-29 also confirmed that the staging credential was accepted and usage was recorded; it did not generate book content or change Pilot 1B.

## Pricing and cost controls

The exact `openai-main-authoring-low` / `gpt-5` rates are configured in **both** databases: USD $1.25 per million input tokens, $0.125 per million cached input tokens, and $10.00 per million output tokens, including reasoning tokens. These are the [official GPT-5 standard API rates](https://developers.openai.com/api/docs/models/gpt-5) checked on 2026-09-29. Recheck official pricing before changing models or after a rate change, then update each environment separately with `kdp pricing set`. Do not assume this profile's rates apply to another provider or model.

Pilot 1B has an audited **hard-stop** budget in both environments: $5 per month, $0.50 estimated maximum per run, warning at 80%. The preflight estimate reserves the configured maximum output plus a conservative input bound; settled cost uses provider token usage and the configured rates. `kdp budget show PROJECT_ID` and `kdp inspect usage TITLE_ID` show local estimates and usage. The provider's billing dashboard remains authoritative for billed amounts. Eleven older Pilot 1B GPT-5 usage events remain unpriced: 26,685 input and 18,408 output tokens. Applying today's rates would yield **about $0.21744**, strictly a comparison estimate rather than historical billed cost. Thus $0 known historical spend does **not** mean those calls were free; the hard-stop cannot account for their unknown actual cost. Do not retroactively present today's rates as their actual historical cost.

For each new project, select the profile and set a hard-stop budget **before** provider-backed generation. Choose operator-approved limits; for example, `kdp budget set PROJECT_ID --monthly-usd 5 --max-run-usd 0.50 --warning-percent 80 --hard-stop`. A project without a budget has no application spending cap. A new model needs its own verified pricing entry; a priced profile alone does not impose a project budget. API-side billing limits and usage reports should also be reviewed because application estimates may differ from final billing.

## Deployment and data boundary

Develop and review changes in the Windows checkout. Run local tests there. Deploy a selected commit or tag to staging as a separate, deliberate action, then verify the staging service and Workspace. Do not make unattended staging changes. Back up staging's SQLite database and corresponding `projects/` artefacts together before changing it; restoring one without the other can break hash and provenance checks.

To start a new book on staging, open the Tailscale Workspace URL above and use **Start a new book**. Enter the project, working title, reader, and idea, choose the ready priced profile, and set operator-chosen monthly and per-request hard limits. Creation itself makes no provider call. The resulting title page exposes concept, planning, chapter drafting, editorial, manual revision, review, verification, build, and release preparation actions. Generative actions require a named operator and explicit cost acknowledgment. Existing project pages can add a title or update provider and limits. Browser operators need no CLI or SSH access; the CLI remains available to system administrators.

The Workspace currently has no application login or user roles. Treat all Tailnet members allowed to reach this service as trusted operators with the ability to submit human decisions; restrict Tailscale ACLs accordingly. This deployment does not add KDP upload or automatic publication.

The development Pilot database originally stored absolute Windows paths. The one-time migration rebased registered paths on staging while retaining content hashes and historical audit/provenance records. Future copies must repeat integrity checks and must not overwrite newer staging work.

## Staging security verification — 2026-09-30

G5 performed read-only service and routing checks and created a restricted pre-change backup. No live service, proxy, Tailscale route, provider setting, project record, or artefact was changed.

Observed staging state:

- `kdp-workspace.service` is active and binds `127.0.0.1:8766`; `kdp-workspace-tailnet.service` (Caddy) is active and binds `100.78.70.2:8767`.
- From the VPS, loopback `/healthz`, the tailnet-bound `/healthz`, and the tailnet-bound Workspace root returned HTTP 200. This confirms availability only; it does not verify access from a different tailnet device.
- The active Caddyfile has no `basic_auth` or `forward_auth`, and no operator identity header is configured in the running app environment. The Workspace root returned 200 without authentication from the VPS. The current proxy rewrites `Host` and `Origin` to loopback but does not validate the browser-facing Origin before rewriting it. Do not treat current tailnet reachability as operator authentication. Until the gated route below is installed and verified, do not use staging for provider-backed actions, approvals, verification decisions, or release actions.
- The exact Tailscale Serve routes observed were:

  | Public/Tailnet listener | Exposure | Loopback target |
  | --- | --- | --- |
  | HTTPS 443 | Funnel (public internet) | `127.0.0.1:3579` |
  | HTTPS 8001 | Tailnet only | `127.0.0.1:8001` |
  | HTTPS 8095 | Tailnet only | `127.0.0.1:8095` |
  | HTTPS 8443 | Tailnet only | `127.0.0.1:3300` |

  The Funnel listener's target process is a separate Node/Next listener, distinct from the Python KDP Workspace service; its `/healthz` returned 404 while KDP's loopback `/healthz` returned 200. Its page content was not inspected and the public route was preserved. No KDP port is currently routed by Serve or Funnel. The existing tailnet policy cannot be inspected from this VPS, so owner-only access is **unverified**.
- The staging checkout is still at `v1.0-platform-complete` and has local modifications. No checkout, pull, restart, or code deployment was performed.

The verified pre-change backup is at `/home/clawusr/.local/backups/kdp-staging/prechange-g5-20260930T133339225637Z`. It contains an SQLite online backup, a paired `projects/` archive, the active Caddyfile and two user service-unit files, plus a Tailscale Serve status snapshot. Its directory mode is `0700`; backup and manifest files are `0600`. The restore-copy test passed SQLite `integrity_check`, found zero foreign-key violations, restored all 87 project files with a matching aggregate tree hash, and verified all 64 registered asset hashes. The source project tree was unchanged during capture. The backup is **not encrypted at file level**; host-disk encryption was not verified. Keep it on this host and do not represent it as encrypted.

The Serve `get-config --all` command returned an empty Tailscale Services configuration; it did not export the node's ordinary Serve routes. The exact current port/status JSON and text snapshots are in the restricted backup. Port 8767 has no current Serve or Funnel route, but it is occupied by the current direct Caddy listener. The intended additive rollback is `tailscale serve --https=8767 off`; it preserves other ports. A complete data recovery, if needed, must restore the SQLite backup and paired artefact archive together during a controlled maintenance window.

### Gated identity path — not installed

Sanitized Caddy and systemd templates are in [`deploy/staging/`](../../deploy/staging/README.md). They describe Tailscale Serve HTTPS on a dedicated tailnet-only port 8767 forwarding to loopback-only Caddy, then to the loopback-only Workspace. Caddy validates the public Host and POST Origin before normalizing them for the app and forwards `Tailscale-User-Login`; the app trusts that header only when `KDP_WORKSPACE_OPERATOR_HEADER=Tailscale-User-Login` is configured. According to the [Tailscale Serve identity-header documentation](https://tailscale.com/docs/features/tailscale-serve), Serve injects this header and removes a client-supplied value, but does not populate identity for tagged client devices.

Before applying this identity route, an operator with Tailscale admin access must restrict TCP 8767 to the intended named operator and user-identity devices, verify that no broad member grant allows other devices, and test an unauthorized device is denied. The correct owner allowlist is not known from the VPS and has not been configured or verified here. These ACL checks remain required before installing the Tailscale Serve identity path. Code-only deployments that keep the existing direct tailnet-bound Caddy listener still require a reviewed immutable revision and a fresh verified backup; they do not establish which tailnet identities are allowed. Do not change the current listener or the unrelated Funnel as part of such a deployment.

## G1-G5 staging deployment - 2026-09-30

The G1-G5 branch was merged and pushed to `main` as `4fabccea53bee656e355a173dbe42542c4614e82`. The VPS checkout is now a clean `main` branch tracking `origin/main` at that revision. The Workspace service imports from `/home/clawusr/apps/kdp-authoring-pipeline/src` and uses that checkout as its data root. The five v1.1 planning/developmental prompt templates are tracked in the merged checkout. The earlier detached release worktree at `/home/clawusr/apps/kdp-authoring-pipeline-release-197cd7b` remains available as a rollback source. Pre-existing local checkout modifications were preserved in Git stash `5b9ee29a3b53e1dd45aad089d6ed687f1427a122`; do not apply them without reviewing the two source-file differences and the saved local documentation.

A fresh owner-only pre-deployment backup is at `/home/clawusr/.local/backups/kdp-staging/predeploy-197cd7b-20260930T141524Z`. Its paired SQLite/project restore check passed: SQLite integrity is `ok`, foreign-key violations are zero, and all 64 registered asset hashes match. Prompt and service configuration snapshots are also included. The backup is not encrypted at file level. The local Windows development database was also migrated to schema version 1 after a paired backup at `C:\Users\Nuburo\.local\backups\kdp-pipeline\premerge-local-migration-20260930T154214Z`; its restore check passed with all 64 registered asset hashes matching.

The app was stopped, `kdp-staging init-db --root /home/clawusr/apps/kdp-authoring-pipeline` was run from the reviewed G1-G5 code, and the Workspace was restarted. The database is now schema version 1 with append-only audit triggers. No project content or provider-backed action was run. Post-deployment doctor reports the schema and audit protections healthy; it continues to warn about 11 historically unpriced usage events, the existing project budget's unpriced usage, and a project with no provider selected.

Post-deployment checks returned HTTP 200 for the loopback health endpoint, the Tailscale-bound health endpoint, and the Workspace page. The existing Caddy listener remains bound to `100.78.70.2:8767`, and the app remains bound to `127.0.0.1:8766`. The Caddy configuration, Tailscale Serve/Funnel routes, and Tailscale ACL were not changed. Host inspection confirms the app port is not bound to a public interface; the Tailscale ACL was not inspected, so this host-level check does not establish which tailnet identities can connect. The separate existing Funnel was preserved.

The active systemd drop-in `/home/clawusr/.config/systemd/user/kdp-workspace.service.d/90-release-197cd7b.conf` sets `PYTHONPATH` to the current `main` checkout. To use the preserved detached release instead, change that path to `/home/clawusr/apps/kdp-authoring-pipeline-release-197cd7b/src`, reload the user manager, and restart the service. The pre-deployment prompt archive is in the backup directory above; use it if reverting to older code that cannot select among v1.0 and v1.1 prompt versions. If database recovery is required, stop the service and restore the paired SQLite database and `projects/` archive together; restoring that pre-deployment backup will discard any staging work created after its timestamp.

## Workspace password login deployment — 2026-09-30

The reviewed revision `8ff7fea` from `codex/workspace-password-auth` is deployed to the staging
checkout in detached-head mode. It adds a single configured username, scrypt password
verification, CSRF-protected sign-in/sign-out, a short session cookie, and a 30-day
**Remember me** cookie. The owner-only auth file is configured outside the repository.

The app fails closed when the account is missing. The staging service template now reads the
out-of-repository owner-only file `/home/clawusr/.config/kdp-workspace/auth.env` and requires
`KDP_WORKSPACE_COOKIE_SECURE=true`. The browser-facing route uses HTTPS for the Secure session
cookie and is available through the tailnet-only Tailscale Serve route
`https://clawsrv.tailbb9d39.ts.net:8767/`. Tailscale Serve owns port 8767 and forwards to
loopback Caddy, which forwards to the loopback Workspace on port 8766. The existing public
Funnel on port 443 was preserved. Smoke tests returned HTTP 200 for `/healthz` and the login
page, and both user services are active. Rotating either the password hash or signing secret
invalidates existing sessions.
