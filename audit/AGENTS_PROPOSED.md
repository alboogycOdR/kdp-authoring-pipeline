# Proposed AGENTS.md update (diff-style rationale, for review)

This is a **proposal**, not an applied change. It adds guardrails the audit found missing (`AGENTS.md` and `docs/CONTRIBUTING_AI.md` steer future agents but say nothing about secrets in commits, security-invariant tests, migrations, cross-OS checks, or the difference between AI-generated and AI-assisted for KDP). Keep the existing precedence chain and mandatory principles; add the italicised items.

## Add to "Mandatory design principles"

- *Canon, prompt templates, and any file whose content affects a decision or a generation are authoritative only when their hash is recorded in SQLite and re-verified on read. Canon files change only through an approved `CanonProposal` applied by the canon-apply service; a non-empty canon file with no recorded hash is a defect.*
- *The audit log is append-only in the database (enforced by triggers), not merely by the absence of an update API. No code path deletes audit events; compensating actions append a new event.*
- *Operator identity used for `actor_id`, `reviewer`, `approver`, `builder` and `creator` must come from an authenticated principal wherever more than one person can reach the Workspace. A typed name is acceptable only for single-owner loopback use, and must be documented as non-authenticating.*
- *A profile may send a credential only to an allow-listed provider host, and only from an environment variable whose name denotes a provider key. Never let a profile forward an unrelated secret.*
- *Truncated, filtered, or refused model output (finish_reason other than `stop`, a refusal, or an incomplete signal) is rejected before it can become an asset, after its usage is recorded. This is not a retry.*
- *KDP disclosure follows KDP's own definitions: text created by an AI tool is AI-generated even after human editing; only content a human created is AI-assisted. Provenance must preserve this distinction per chapter, and the release AI-use count must include human-edited AI content.*

## Add to "Engineering and change-management rules"

- *Never commit secrets, canary or otherwise, in code, tests, evidence, logs, or reports. Scan changed files before committing.*
- *Any change to the SQLite schema goes through the versioned migration mechanism and sets `PRAGMA user_version`; it must upgrade cleanly from every tagged historical schema. Never hand-edit stored rows or paths; use the supported relocate/migration commands.*
- *Text artefacts are written with LF line endings and durably (fsync) so content hashes are portable across Windows (dev) and Linux (staging) and survive power loss.*
- *Security-critical behaviour (state-machine edges, budget gate, acceptance/approval, canon apply, verification blockers, provider adapter error paths, Workspace host/origin/CSRF and path validation) must be covered by tests that fail when the control is removed. Track a mutation-score floor for these modules.*
- *There is no CI in the repository; until there is, run `pytest`, the proposed `ruff` set, `mypy` (baseline), `pip-audit`, and a secret scan locally before declaring work complete, and report exact results.*

## Add to "Operating Environments"

- *The Workspace has no application authentication; on staging the Caddy proxy neutralises the app's Host/Origin defences. Restrict Tailscale ACLs to the owner's devices, authenticate at the proxy, and commit the proxy configuration. Do not add a second operator or expose the port until identity is authenticated.*

## Note for the "Mandatory design principles" already present

Two current principles are stated as facts but were **broken** at the audited commit and should not be cited as guarantees until the fixes land: "No canon mutation … without an approved CanonProposal" (AUD-012) and "Every workflow state mutation must be auditable" (AUD-021, mutable audit rows). Keep them as requirements; add the enforcement items above so they become true.
