# Proposed fixes (not applied to the baseline)

`ALL-KDP-AUD-fixes.patch` is the complete, verified set. The other files split it by area for review; they are mutually consistent with ALL but some depend on each other (apply ALL unless reviewing).

Verification (clean checkout of `91c48ad`, 2026-09-29):

- `git apply --check ALL-KDP-AUD-fixes.patch` — clean
- original suite on patched tree — **122 passed, 1 skipped**
- `KDP_AUDIT_TARGET=<patched> bash audit/run_audit.sh` — **33 passed** (baseline: 27 failed, 6 passed)
- ruff F/E9 error count unchanged (9 → 9)

| Patch | Findings | Behaviour change to review |
|---|---|---|
| `KDP-AUD-003-015-016-004-state-and-release-gates.patch` | 003, 004, 015, 016 | `transition` to ASSET_READY / PREFLIGHT_PASSED / KDP_DRAFT_READY needs recorded evidence; `accept_chapter(supersede=True, supersede_reason=…)` + CLI `--supersede-reason`; release approval blocked in hold/post-submission states and when approver == preparer/checker; one existing test updated to use a distinct checklist reviewer |
| `KDP-AUD-005-006-context-truth.patch` | 005, 006 | New prompt versions `developmental-v1.1`, `planning/*-v1.1` carry context; v1.0 retained for historic provenance; callers render explicit versions |
| `KDP-AUD-007-009-010-013-022-023-029-030-provider-and-generation.patch` | 007, 009, 010, 013, 022, 023, 029, 030 | Configured rates win over provider `cost`; `KDP_PROVIDER_HOST_ALLOWLIST` (default `api.openai.com`, loopback always allowed); deny-list for non-provider secret names; truncated/filtered/refused output rejected after usage is recorded; operator re-run after failure creates `…:attempt-N`; 4 MiB response cap; tolerant usage parsing; template hash in provenance; `README.md` in `prompts/` ignored. `tests/conftest.py` allow-lists the fixture host |
| `KDP-AUD-011-014-031-032-044-content-integrity.patch` | 011, 014, 031, 032, 044 | Continuity heuristics only outside a valid JSON contract; broadened placeholder + unfinished-text blockers; AI lineage `AI_GENERATED_HUMAN_EDITED`; heading removal only once; `revise` filenames recognised |
| `KDP-AUD-012-021-027-040-041-042-043-durability-and-doctor.patch` | 012 (detection), 021, 026, 027, 040, 041, 042, 043 | FK enforcement (deferred to commit via explicit BEGIN), 15 s busy timeout, `user_version=2` with newer-DB refusal, append-only audit triggers, compensation appends instead of deleting, `provenance.prompt_template_sha256` column, fsync on text/JSON writes, LF normalisation, `kdp relocate`, extended `doctor` |
| `KDP-AUD-017-018-019-034-workspace-server-hardening.patch` | 017, 018, 019, 034 | Security headers on every response, 30 s socket timeout, catch-all 503, path-only access log |

Not patched (design only): AUD-001/002 (authentication and proxy — `HARDENING_STAGING.md`), AUD-020, 025, 028, 033, 035–038, 045–049.

Migration notes: the patch adds a nullable column and triggers on first `init_db`; it sets `PRAGMA user_version=2`. Pre-patch code performs no version check and will still open the database (the gap AUD-041 describes); any later release that has a lower `SCHEMA_VERSION` than the file will refuse to open it. Roll back by restoring the pre-upgrade backup, not by running older code. Back up `.kdp/state.db` and `projects/` together before upgrading. Normalising line endings changes the hash of *newly written* CRLF text only; existing artefacts are untouched.
