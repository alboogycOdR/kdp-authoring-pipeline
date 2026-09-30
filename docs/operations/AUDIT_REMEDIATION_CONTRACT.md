# Audit Remediation Contract

## Purpose and limits

This contract turns the findings in `audit/` into bounded, reviewable remediation work. The audit bundle is evidence and proposal material, not an applied patch or an authority to broaden architecture. Confirm each finding against the current branch before changing behavior. Preserve backwards compatibility and the existing approval, provenance, and audit requirements in `AGENTS.md` and the Master Architecture Pack.

This remediation may fix the confirmed defects listed below, add focused regression tests, correct documentation that describes those defects, and harden the existing staging deployment. It does not authorize provider calls, new book content, automatic approvals, public exposure, KDP upload/publication, or changes to Pilot 1B content.

## Confirmed remediation scope

The audit's clean-checkout patch and test results are leads to verify, not proof that the current checkout or staging installation is fixed. The implementation must preserve the finding-to-test link and meet these observable outcomes:

| Workstream | Findings | Acceptance criteria |
|---|---|---|
| SQLite, artefact durability, and inspection | AUD-012 (detection only), AUD-021, AUD-026, AUD-027, AUD-040–043; schema support for AUD-029 | Canon changes are detected unless applied through the approved proposal flow; audit events cannot be silently edited/deleted and compensation is auditable; durable writes, relocatable paths, schema-version checks, enforced foreign keys, stable line-ending hashes, and doctor checks are covered by regression tests. Existing supported databases upgrade safely; newer unsupported schemas fail clearly. |
| Workflow, acceptance, build, and release gates | AUD-003, AUD-004, AUD-014–016, AUD-031–032 | State transitions require their recorded evidence; chapter acceptance checks title state and chapter number; superseding is explicit, reasoned, and audited; hold states and separation-of-duties rules block release approval; unresolved placeholders block builds; AI lineage is not lost on human edits; heading cleanup removes only the intended heading. |
| Provider, prompt context, usage, and output integrity | AUD-005–007, AUD-009–011, AUD-013, AUD-022–023, AUD-029–030 | Each generation request contains the source content its manifest claims; configured pricing remains authoritative; provider egress and environment-variable selection are constrained; incomplete/refused/truncated responses do not create assets while available usage is retained; valid continuity findings survive parsing; retries are explicit new attempts; response size is bounded; malformed usage is handled safely; prompt version and hash are traceable. |
| Workspace request, identity security, and review routing | AUD-001, AUD-017–019, AUD-034, AUD-044, AUD-050, AUD-053 | When identity enforcement is configured, unauthenticated requests cannot mutate state and actor identity comes from the trusted proxy path, not a typed form value; same-origin checks, security headers, request timeout, safe error handling, path-only access logs, and HEAD/GET behavior have regression coverage. Workspace review recognizes supported revision filenames and routes those assets through the existing review flow. |
| Staging deployment | AUD-002 and staging controls in `audit/HARDENING_STAGING.md` | Sanitized, reviewable proxy/service configuration is documented; the application is reachable only through Tailscale and trusted authenticated access; forwarded identity cannot be client-forged; host/origin checks are compatible with the actual proxy. Smoke checks prove unauthenticated access is denied and authorized access works. Do not expose the service publicly. |
| Documentation truth | AUD-039, AUD-045 | Correct only claims shown by the implemented and inspected system; remove sensitive staging details from public-facing documentation without copying secrets into the repository. |

The security, quality, and workflow tests supplied under `audit/tests/` are regression inputs. They must be run against the implementation being changed; the audit's reported patched-tree results are not a substitute for current-run results.

## Proposed or deferred work

The audit identifies these as designs, analytical risks, or backlog proposals rather than verified patch fixes. This remediation contract does **not** authorize their implementation:

- AUD-002 proxy topology is not lab-reproduced; verify it against the real sanitized staging configuration as part of the staging workstream.
- AUD-020 performance redesign; AUD-025 DOCX/EPUB and metadata/export workflow; AUD-028 target-reader context; AUD-033 readiness endpoint; AUD-035 CLI generation-control parity; AUD-036 editor limits; AUD-037 matter-add allow-list; AUD-038 CI/lint/type/lockfile program; AUD-046 packaging; AUD-047 originality/audience-safety gate; AUD-048 finding-severity acceptance policy; AUD-049 broader UX recommendations.
- Proposed Scripture licensing model, originality/safety gates, new backup/restore or budget-alert systems, broad refactors, and proposed ADR or `AGENTS.md` changes.

These items require a separately scoped and explicitly approved decision or milestone. AUD-012 is limited here to detection/integrity enforcement described above; implementing a new canon-application workflow requires separate review if it exceeds existing approved conventions.

## Global acceptance checks

1. No audit finding is called fixed without a current regression test or an explicit, documented manual staging check for environment-dependent behavior.
2. No provider call, automatic approval, publication, upload, or Pilot 1B content change occurs during remediation.
3. Existing supported database and artefact compatibility is preserved; any required migration is reviewed, tested from a pre-change database, and has a backup/rollback procedure.
4. No secrets, credentials, or manuscript content are added to logs or diagnostic output.
5. Before declaring remediation complete, run `pytest -v`, `python scripts/pilot_dry_run.py`, and `git diff --check`; report results and unresolved findings. Keep commits, pushes, merges, and staging deployment subject to their separately authorized steps.
