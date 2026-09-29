# Security, integrity and publishing backlog

Each item: title · priority (P0 before next paid generation / P1 before second operator / P2 before first KDP publication / P3 hardening) · acceptance criteria · the test that must pass. Tests live in `audit/tests/`.

| # | Item | P | Acceptance criteria | Test |
|---|---|---|---|---|
| B-01 | Authenticated operator identity (AUD-001) | P1 | Proxy authenticates (Tailscale identity or basic/forward auth); app accepts identity only from a configured trusted header and only from the proxy's address; `operator`/`reviewer` form fields removed or ignored; `actor_id` = authenticated identity; unauthenticated request → 401 | new `test_workspace_requires_identity` |
| B-02 | Proxy configuration in repo (AUD-002) | P1 | Caddyfile (or systemd + Caddy templates) committed; site bound to exact IP:port; other Host → 421 at proxy; Origin allow-list at proxy; documented in ENVIRONMENTS.md | config review + smoke test |
| B-03 | Release evidence behind state transitions (AUD-003) | P0 | ASSET_READY/PREFLIGHT_PASSED/KDP_DRAFT_READY refused without unblocked build / unblocked candidate / approved candidate | `test_KDP_AUD_003_*` |
| B-04 | Explicit chapter supersede (AUD-004) | P2 | CLI + service + Workspace review control; old version archived, row `superseded`, audited; rebuild clears the old condition | `test_KDP_AUD_004_*` |
| B-05 | Context truth for every prompt family (AUD-005/006) | P0 | For every family, manifest input set == set of assets whose text is in the request (automated diff test per family) | `test_KDP_AUD_005_*`, `test_KDP_AUD_006_*` |
| B-06 | Configured pricing authoritative (AUD-007) | P0 | Provider `cost` never lowers recorded cost; stored as detail | `test_KDP_AUD_007_*` |
| B-07 | Provider egress allow-list (AUD-009) | P0 | Remote host must be allow-listed; env name deny-list; re-validated at resolve | `test_KDP_AUD_009*` |
| B-08 | Reject incomplete completions (AUD-010) | P0 | `length`/`content_filter`/refusal → job failed, usage recorded, no asset; review page shows finish reason | `test_KDP_AUD_010_*` |
| B-09 | Continuity heuristic precision (AUD-011) | P3 | Valid confirmed JSON with "missing …" findings accepted | `test_KDP_AUD_011_*` |
| B-10 | Canon apply workflow + anchored canon hash (AUD-012) | P2 | Canon written only by `apply_canon_proposal(accepted)`; hash in SQLite; continuity refuses unanchored canon; doctor fails mismatch | `test_KDP_AUD_012_*` + new apply test |
| B-11 | Deliberate retry (AUD-013) | P3 | Operator re-run creates new attempt job; never automatic | `test_KDP_AUD_013_*` |
| B-12 | Placeholder / unfinished text blockers (AUD-014) | P2 | Variants, TODO/TBD/TK/lorem block builds; Hypothesis fuzz of detector | `test_KDP_AUD_014_*` |
| B-13 | Release approval holds + SoD (AUD-015) | P1 | Hold states block; approver ≠ creator/checkers (identity from B-01) | `test_KDP_AUD_015_*` |
| B-14 | Acceptance state & number checks (AUD-016) | P1 | Title in DRAFTING; filename number == chapter_number | `test_KDP_AUD_016_*` |
| B-15 | Append-only audit + hash chain (AUD-021) | P1 | Triggers present (doctor FAIL if absent); `prev_hash`/`event_hash` chain verified by `kdp verify-audit` | `test_KDP_AUD_021_*` + chain test |
| B-16 | AI disclosure lineage (AUD-031) | P2 | Any asset with AI lineage counted; disclosure statement pre-filled from provenance per chapter | `test_KDP_AUD_031_*` |
| B-17 | Scripture licence model | P2 | Verification item records translation, verse count; build totals verses per translation and flags >500 / ≥25% / whole-book; generates required notice text for human review | new |
| B-18 | Originality gate (AUD-047) | P2 | Shingle (k=8 words) overlap vs `02_sources/` and prior titles; overlap > threshold → blocker requiring rights decision | new |
| B-19 | Audience/safety pass (AUD-047) | P2 | Deterministic checks (PII patterns, medical/financial promise phrases) + optional model pass whose findings are blockers with waiver | new |
| B-20 | Server robustness (AUD-017/018/019) | P1 | Headers on all responses; socket timeout; 503 on unhandled errors; connection cap at proxy | patch + new HTTP smoke test |
| B-21 | Access log + cost alert (AUD-034) | P1 | Path-only access log to journald; daily spend summary; alert when monthly ≥ warning % | new |
| B-22 | Durable writes, FK, schema version (AUD-026/041/042) | P3 | fsync; FKs enforced; `user_version` | `test_KDP_AUD_041/042_*` |
| B-23 | Relocate/backup/restore tooling (AUD-027) | P1 | `kdp backup` (SQLite `.backup` + tar + hash manifest), `kdp restore --verify`, `kdp relocate` | `test_KDP_AUD_027_*` + new backup test |
| B-24 | Doctor completeness (AUD-040) | P1 | Manifests, approvals, canon, triggers, paths, orphans (`*.tmp`), running jobs older than timeout | `test_KDP_AUD_040_*` |
| B-25 | CLI parity for generation controls (AUD-035) | P1 | CLI generation requires hard-stop budget unless `--allow-unbudgeted` (audited) | new |
| B-26 | CI (AUD-038) | P1 | GitHub Actions: 3.12 + 3.13, pytest, ruff (proposed config), mypy baseline ratchet, pip-audit, gitleaks, audit suite on patched state | pipeline green |
| B-27 | Remove staging details from public docs (AUD-045) | P3 | IP/account/key path moved to private ops note | review |
| B-28 | Finding severity gates acceptance (AUD-048) | P2 | Open critical / continuity-fail findings block acceptance unless waived with rationale | new |
