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
