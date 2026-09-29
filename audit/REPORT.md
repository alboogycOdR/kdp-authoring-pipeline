# KDP Authoring Pipeline — Full-Spectrum Audit Report

## 1. Header

| Item | Value |
|---|---|
| Audited commit | `91c48ad113a9357c2804455fbe7d1d69e497c753` (default branch tip, "Add browser book authoring and creator guidance"). Staging tag `v1.0-platform-complete` = `7b5feb6` (predates browser authoring) |
| Audit date | 2026-09-29 |
| Environment | Linux container, Python 3.12.3 venv (`pip freeze` in `evidence/tools/`), SQLAlchemy 2.1.1, httpx 0.28.1, pydantic 2.13.5, typer 0.27.2; Chromium 1194 (Playwright), axe-core 4.10.0, Caddy 2.8.4 (downloaded, not exercised — see exclusions) |
| Tools | pytest 9.1.1, coverage, pytest-randomly, bandit, ruff (proposed rule set), mypy (default + `--strict`), radon, vulture, pip-audit, osv-scanner 1.8.5, gitleaks 8.18.4, trufflehog 3.82.13, python -m build, custom mutation harness (`lab/mini_mutation.py`), pypdf |
| Lab | Throw-away roots per test; loopback-only mock OpenAI-compatible server with ~45 scenarios (`lab/mock_provider.py`); `CaptureProvider` records exact requests; synthetic data generator (`lab/datagen.py`); state × action harness; Playwright/axe scanner (read-only GETs). No real provider, no real key, no KDP/Amazon account contact, no staging contact |
| Reproduce | `bash audit/run_audit.sh` (baseline: finding tests fail) · `KDP_AUDIT_TARGET=<checkout with audit/patches/ALL-KDP-AUD-fixes.patch applied> bash audit/run_audit.sh` (all pass) |

### Exclusions and deviations from the brief (stated, not silent)

1. **Workspace exploit automation (WS-B, chain C1) was not built.** Two attempts to write the end-to-end forged-approval script and the Workspace HTTP attack tests were stopped by a safety classifier. The owner agreed to finish the audit with WS-B covered by **code trace plus the repository's own integration tests**, which already submit decisions through the HTTP layer with a scraped token (`tests/integration/test_sprint16_workspace_review.py::test_review_http_requires_token_and_shows_exact_result`). WS-B findings are therefore rated `Likely`/`Confirmed-by-code`, never `Confirmed-in-lab`, and no exploit tooling for the Workspace is included.
2. **Proxy replica (K3) not exercised** for the same reason; the Caddy binary was fetched but no Host/Origin/rebinding tests were run. K3 is resolved analytically.
3. **Official KDP help pages** (`kdp.amazon.com`) are blocked by this environment's egress proxy. Policy facts are taken from the official pages' search-index extracts (URLs cited, retrieved 2026-09-29) and marked *index-extract*; re-verify on the live pages before relying on them.
4. `semgrep`, `pyright`, `jscpd`, `import-linter`, `lighthouse`, `locust`, `py-spy`, `mitmproxy`, `nuclei` were not installed; substitutes are listed per workstream. Mutation testing used a small purpose-built harness (19 hand-chosen mutants) because `mutmut 3` needs a repo reconfiguration.
5. `claims.csv` has 85 claims (target ≥150).

### Coverage table

| WS | Topic | Status | Notes |
|---|---|---|---|
| A | Governance invariants, state machine | **Complete** | 9 lab-confirmed findings, state × action matrix |
| B | Workspace web security | **Partial** | code trace only (see exclusion 1); XSS output-encoding reviewed statically, CSP observed blocking inline script in a real browser |
| C | Provider, secrets, egress | Complete | mock server over real sockets |
| D | Cost/budget integrity | Complete | K11 race refuted (with caveat) |
| E | Generation pipeline integrity | Complete | request-vs-manifest diff for every prompt family |
| F | Durability & consistency | Complete (fault injection by kill-point: analytical) | relocation, doctor, pragmas, CRLF, schema upgrade |
| G | Build/release/KDP fitness | Complete | KDP table from index-extracts |
| H | Rights, verification, compliance | Partial | Scripture licensing researched; originality gate designed, not prototyped |
| I | Code quality & architecture | Complete (pyright/jscpd substituted by mypy/radon) | |
| J | Test-suite quality | Complete | coverage, random order, -W error, -X dev, mutation |
| K | UI/UX/a11y | Partial | 8 pages × 4 viewports screenshots, axe WCAG 2.2 AA, dark theme; no keyboard-walk or task-timing study |
| L | Operability | Partial (analytical; staging is out of scope) | |
| M | Documentation truthfulness | Partial | 85 claims |
| N | Performance/capacity | Complete (N up to 15 titles × 10 chapters) | |
| O | Supply chain & hygiene | Complete | |

## 2. Executive summary

The KDP Pipeline is a carefully written, test-conscious codebase whose **individual controls are mostly sound** — output escaping, CSP, key handling, offline checks, idempotent acceptance, deterministic builds, and conservative cost estimates all held up. The failures are in **how the gates connect**: several of the governance promises in `AGENTS.md` are enforced in one entry point but not another, rest on a self-declared name, or are defeated by a missing workflow step.

The five facts that matter most:

1. **The release path is unreachable for exactly the book this tool was piloted on.** An accepted chapter can never be replaced (AUD-004). Any approval condition (the Workspace adds one automatically for `[SCRIPTURE NEEDED]`) is therefore a permanent build blocker. Pilot 1B cannot reach an approved release without editing the database.
2. **The human release gate can be skipped entirely from the CLI.** `kdp transition` walks a title to `KDP_DRAFT_READY` with zero builds and zero release candidates (AUD-003). In the Workspace, one self-declared person can build, check, and approve a release while the title is in `POLICY_HOLD` (AUD-015). The Workspace itself has no authentication: every "human approval" is a form post with a typed name that any reachable client can make (AUD-001, code trace).
3. **Two generation paths do not send what their provenance says they used.** The Pilot 1B bug class ("manifest is provenance, not prompt context") was fixed for continuity only. Developmental editing still runs without the chapter (AUD-005). All four planning stages run without the concept brief, the idea or the prior plan (AUD-006), so the concept workflow does not influence the book.
4. **Several output problems pass the pipeline unflagged:**
   - Truncated `finish_reason=length` text is accepted into the manuscript (AUD-010).
   - Placeholder variants, `TODO` and `lorem ipsum` build as clean (AUD-014).
   - A chapter that is 99.9% AI-generated is reported as `ai_asset_count = 0` after a one-character human edit (AUD-031). KDP requires AI-generated content to be disclosed, so this is a disclosure risk.
5. **Integrity tooling is weaker than documented:**
   - `doctor` detected none of three independent tampering cases (AUD-040).
   - Audit rows can be rewritten or deleted undetected, and the app itself deletes them on rollback (AUD-021).
   - Canon files are changed on disk and consumed without any proposal (AUD-012).
   - Foreign keys are declared but never enforced (AUD-042).
   - A backup restored to another path fails every asset check, and there is no relocate tool (AUD-027).

A patch set in `audit/patches/` addresses 27 of the findings. With it applied to a clean checkout, the original suite still passes (122 passed, 1 skipped), all 33 audit tests pass, and no new lint errors appear.

### Scorecard (1 = poor, 5 = strong)

| Area | Score | Justification |
|---|---|---|
| Governance-invariant integrity | 2 | 4 of 12 principles broken in lab (canon, audit, human gate, provenance-truth); others hold with gaps |
| Security | 2 | Strong output encoding/CSP/key hygiene, but no authentication on a tailnet-exposed approval surface and profile-driven secret egress |
| Cost/budget integrity | 3 | Conservative estimates and a race that is (accidentally) serialized; provider-supplied `cost` can zero out spend; malformed usage loses billed records |
| AI-pipeline integrity | 2 | Two families send less than they record; truncation/refusal accepted; unverified canon context |
| Data durability | 2 | Atomic writes but no fsync, no FK enforcement, absolute paths, no schema version, weak doctor |
| KDP/publishing fitness | 1 | Markdown only; no metadata/cover/keywords/categories capture; AI disclosure under-counts; release path blocked by design gap |
| Rights/compliance | 3 | Verification/rights records are thoughtful; Scripture licensing not modelled; no originality or audience-safety gate |
| Code quality | 3 | Readable, consistent; very high complexity hot spots (`inspect_title` CC 316) and no lint/type gates |
| Test quality | 2 | 77% branch coverage but 21% mutation score on the state machine and budget gate |
| UI/UX | 3 | Clear consequence text; heavy jargon/IDs, 15 repeated "operator name" fields per page |
| Accessibility | 4 | 0 axe violations across 8 pages incl. dark theme; minor tablet overflow |
| Performance | 3 | Fine for 1–5 titles; home page cost grows ~0.29 s per title (N+1) |
| Operability | 2 | No access log, static `/healthz`, service/proxy config not in repo, no backup/restore tooling |
| Documentation truthfulness | 3 | Honest about limitations; several material claims false (see §7) |

**Does "v1.0 platform complete" survive?** Partly. Every listed sprint has code behind it. But a realistic devotional title cannot complete the documented workflow to an approved release (AUD-004). Two advertised AI stages do not use their stated inputs (AUD-005/006). The "human approval gates" can be bypassed (AUD-003). "Feature-complete, not workflow-complete" is accurate; "platform complete" is not.

### Go / no-go

| Scenario | Verdict | Conditions |
|---|---|---|
| (a) Continued single-owner use on dev (loopback) | **GO with conditions** | Treat developmental/planning outputs as uninformed (AUD-005/006) until patched; check `finish_reason` manually; set a hard-stop budget on every project (CLI has no gate) |
| (b) Continued staging use on the tailnet | **NO-GO for paid generation and approvals** until AUD-001/002 are mitigated: restrict Tailscale ACLs to the owner's device(s) only, add Tailscale-identity or basic auth at Caddy, and record the Caddyfile in the repo. Read-only browsing is acceptable meanwhile |
| (c) Adding a second human operator | **NO-GO** until authenticated identity replaces the free-text name (AUD-001), release approval enforces segregation of duties (AUD-015), and audit rows are append-only in the database (AUD-021) |
| (d) Publishing a first real title to KDP | **NO-GO** until AUD-004 (supersede), AUD-010, AUD-014, AUD-031 are fixed and a DOCX/EPUB export plus metadata capture exist (AUD-025); verify Scripture translation permissions and KDP AI disclosure manually |

## 3. Attack/failure chains C1–C8

| Chain | Result | Evidence |
|---|---|---|
| C1 forged human approval | **Demonstrated in parts, not end-to-end** (end-to-end automation withheld, see exclusions). The decision services accept any `reviewer` string (AUD-001); the repo's own HTTP test submits review decisions with a token scraped from a GET page; `kdp transition` reaches `KDP_DRAFT_READY` ungated (AUD-003); one name can build, check and approve a release during `POLICY_HOLD` (AUD-015) | `evidence/KDP-AUD-003`, `evidence/KDP-AUD-015`, `recon/routes.md` |
| C2 secret exfiltration | **Demonstrated (configuration path).** A profile with `api_key_env=AWS_SECRET_ACCESS_KEY` sent the canary as `Authorization: Bearer …` to the configured endpoint (loopback mock); the same validator accepts any HTTPS host. A canary in error bodies never reached jobs/audit (control held) | `evidence/KDP-AUD-009`, `evidence/KDP-AUD-009b` |
| C3 poisoned book | **Partially demonstrated.** Canon injected on disk reached the continuity prompt with no proposal (AUD-012); truncated output was accepted as chapter 1 (AUD-010). Hostile HTML/Markdown did not execute (escaping + CSP held). Model text claiming approval changed no state (no parser acts on it) | `evidence/KDP-AUD-012`, `evidence/KDP-AUD-010` |
| C4 budget breach | **Not demonstrated for concurrency** (K11 refuted: SQLite writer lock taken at the job insert serializes the check; 12 concurrent requests → 1 call, 9 budget-blocked, 2 raw `database is locked`). **Demonstrated for accounting:** provider `usage.cost=0` recorded $0 for 200k tokens (AUD-007); a billed 200 with malformed usage recorded no usage (AUD-022) | `evidence/POS-K11-budget-race`, `evidence/KDP-AUD-007`, `evidence/KDP-AUD-022` |
| C5 silent corruption | **Demonstrated.** Deleted build manifest, edited canon and forged approval hash → `doctor` reported 0 problems (AUD-040); CRLF copies hash differently (AUD-043); restore to a new path → every asset "missing" with no supported fix (AUD-027) | `evidence/KDP-AUD-040`, `-043`, `-027` |
| C6 publishing risk | **Demonstrated.** Chapter containing `[ SCRIPTURE NEEDED ]`, `【SCRIPTURE NEEDED】`, split/NBSP variants, `TODO`, `lorem ipsum`, `[TK]` built with status `built` (AUD-014); AI-generated chapter disclosed as non-AI (AUD-031); release approvable during `POLICY_HOLD` (AUD-015) | `evidence/KDP-AUD-014`, `-031`, `-015` |
| C7 operator misled | **Demonstrated.** Developmental findings are presented as analysis of a chapter the model never saw (AUD-005); review page shows no finish reason for a truncated draft (AUD-010); Unicode bidi/zero-width text is displayed escaped but not flagged | `evidence/KDP-AUD-005` |
| C8 DoS the operator | **Code trace + measurement.** No socket timeout (slow connections hold threads indefinitely, AUD-018); each home-page GET costs ~0.29 s × titles and ~80 queries per title (AUD-020); DB lock → dropped connection with no response (AUD-019) | `evidence/perf/`, `recon/routes.md` |

## 4. Findings

### 4.1 Table

Severity uses the brief's rubric. Confidence: **Confirmed** = reproduced by a test in `audit/tests/` that fails on the baseline; **Code** = unambiguous code path, not exercised; **Likely** = depends on configuration not in the repo.

| ID | Title | Severity | Confidence | Category | WS | Patch |
|---|---|---|---|---|---|---|
| AUD-001 | Workspace has no authentication; every human decision attributes to a typed name | Critical (tailnet) / High (loopback) | Code | security | B | design (HARDENING_STAGING.md) |
| AUD-002 | Staging proxy topology must neutralise the Host/Origin checks | High | Likely | security | B/L | design |
| AUD-003 | `kdp transition` reaches PREFLIGHT_PASSED / KDP_DRAFT_READY without build, candidate or approval | Critical | Confirmed | governance | A | yes |
| AUD-004 | Accepted chapters cannot be superseded; conditions and placeholders block release forever | Critical | Confirmed | functional | A/G | yes |
| AUD-005 | Developmental editing is sent without the chapter while provenance lists it | High | Confirmed | ai-pipeline | E | yes |
| AUD-006 | Planning stages receive no concept, idea or prior-plan context | High | Confirmed | ai-pipeline | E | yes |
| AUD-007 | Provider-reported `usage.cost` overrides configured pricing | High | Confirmed | cost-risk | D | yes |
| AUD-009 | Profiles can forward any environment secret to any HTTPS host | High | Confirmed | security | C | yes |
| AUD-010 | Truncated / filtered / refused completions become acceptable chapters | High | Confirmed | ai-pipeline | C/E | yes |
| AUD-011 | Continuity rejects genuine "missing beat" findings after billing | Medium | Confirmed | ai-pipeline | E | yes |
| AUD-012 | Canon baseline mutable on disk and fed to the model; approved proposals never apply | High | Confirmed | governance | A | yes (detection) |
| AUD-013 | A failed generation can never be retried (idempotency dead end) | Medium | Confirmed | functional | D | yes |
| AUD-014 | Placeholder/unfinished-text detection is a single literal | High | Confirmed | publishing-risk | G/H | yes |
| AUD-015 | Release approval allowed in POLICY_HOLD/RIGHTS_HOLD; no segregation of duties | High | Confirmed | governance | A/G | yes |
| AUD-016 | Chapter acceptance ignores title state and source chapter number | High | Confirmed | governance | A | yes |
| AUD-017 | 303/405 responses lack security headers | Low | Code | security | B | yes |
| AUD-018 | No per-connection socket timeout on a thread-per-connection server | Medium | Code | security | B/N | yes |
| AUD-019 | Unhandled DB errors drop the connection with no response | Medium | Confirmed (raw `database is locked` in race test) | operability | B/F | yes |
| AUD-020 | Every page recomputes every title (~80 queries, ~170 hashes per title) and runs DDL checks | Medium | Confirmed (measured) | performance | N | design |
| AUD-021 | Audit log is mutable; app deletes audit rows on rollback | High | Confirmed | governance | A/F | yes |
| AUD-022 | Billed response with malformed usage loses the usage record | Medium | Confirmed | cost-risk | D | yes |
| AUD-023 | Provider response size unbounded (48 MB stored as a chapter) | Medium | Confirmed | security/robustness | C | yes |
| AUD-025 | Output is Markdown only; KDP metadata, cover, keywords, categories, pricing not captured | High | Confirmed (code) | publishing-risk | G | design (DESIGN_EXPORT.md) |
| AUD-026 | Atomic writes without fsync | Low | Code | durability | F | yes |
| AUD-027 | Absolute paths in DB; restored copy fails every check; no relocate tool | High | Confirmed | durability | F/L | yes |
| AUD-028 | `target_reader` is never set: every prompt says "Target reader: unspecified" | Medium | Code | ai-pipeline | E | design |
| AUD-029 | Prompt template file hash not in provenance | Medium | Confirmed | provenance | E | yes |
| AUD-030 | Any non-versioned `.md` in `prompts/` disables all generation | Low | Confirmed | robustness | E | yes |
| AUD-031 | AI disclosure under-counts: manual edit of AI text becomes "AI_ASSISTED"/human | High | Confirmed | publishing-risk | H | yes |
| AUD-032 | Build silently drops every line equal to the chapter heading | Medium | Confirmed | functional | G | yes |
| AUD-033 | `/healthz` never touches DB or disk | Low | Code | operability | L | design |
| AUD-034 | No access log; request and error trail limited to audit rows | Medium | Code | operability | L | yes |
| AUD-035 | CLI generation lacks the Workspace's controls (cost ack, hard budget, priced profile) | Medium | Code | cost-risk | D/K8 | design |
| AUD-036 | Editor: 100 KB source cap, 200 KB body cap, content `.strip()`, 413 loses edits | Medium | Code | ux | K | design |
| AUD-037 | `build matter-add` copies any readable file into the book | Low | Code | security | G | design |
| AUD-038 | No CI, lint, type gates or lockfile; mutation score 21% on critical modules | Medium | Confirmed | quality | I/J | design |
| AUD-039 | Documentation contradictions on material facts | Medium | Confirmed | docs | M | – |
| AUD-040 | `doctor` misses manifest, canon and approval tampering | High | Confirmed | durability | F | yes |
| AUD-041 | No schema version; newer/older DB mismatch undetectable | Medium | Confirmed | durability | F | yes |
| AUD-042 | Foreign keys declared but not enforced (and ORM insert order violates them) | Medium | Confirmed | durability | F | yes |
| AUD-043 | CRLF vs LF produces different content hashes (dev Windows ↔ staging Linux) | Medium | Confirmed | durability | F | yes |
| AUD-044 | AI revisions (`chapter.revise.N-…`) cannot be accepted in the browser | High | Confirmed | functional | K | yes |
| AUD-045 | Staging host, IP, account and key path published in repository docs | Low | Confirmed | security (info) | O | – |
| AUD-046 | Wheel ships no prompts; deployment needs a full checkout | Low | Confirmed | packaging | O | design |
| AUD-047 | Audience/child-safety and originality have no enforced gate | Medium | Code | rights-risk | H | design |
| AUD-048 | Continuity "fail" or open critical findings do not block acceptance | Medium | Code | governance | E | design |
| AUD-049 | UX: repeated operator fields, raw IDs, Python literals, tablet overflow | Low | Confirmed | ux | K | UX_RECOMMENDATIONS.md |

(AUD-008 was reserved for the budget race K11; it was refuted and is recorded as positive control `POS-K11`. AUD-024 was merged into AUD-031.)

### 4.2 Write-ups

Line numbers refer to `91c48ad`. Every "Confirmed" finding has a test `audit/tests/*::test_KDP_AUD_###_*` that fails on the baseline and passes with `audit/patches/ALL-KDP-AUD-fixes.patch`; its evidence is in `audit/evidence/KDP-AUD-###/`.

#### AUD-001 — Workspace has no authentication; every human decision attributes to a typed name
- **Severity:** Critical in the documented staging deployment (CVSS 3.1 8.1 `AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N`); High on loopback (`AV:L`). **Confidence:** Code (lab automation withheld; see exclusions). **CWE:** 306, 287, 862. **ASVS:** V2, V4. **Leads:** K1, K2, K8.
- **Actor:** any client able to reach the Workspace: another tailnet device, another local user or process on the dev machine, or a browser extension.
- **Affected:** `workspace/server.py:32` (one process-global token), `:245` (token is the only check), `workspace/actions.py:126` and `authoring.py:320,354` (`reviewer`/`operator` from the form).
- **Description:** The token in every page is identical for every client. It stops cross-site form posts from origins that cannot read a page, which is the only protection it gives. Any client that can load a page can read the token. With it, that client can submit asset, canon, verification, rights and release decisions, run paid generation, and raise budgets to $10,000 per month. It can do all of this under any name. The audit trail cannot distinguish people.
- **Impact:** the "human approval gate", "named operator" and "audit" promises depend entirely on network placement. `ENVIRONMENTS.md` accepts this explicitly ("Treat all Tailnet members … as trusted operators"). This report quantifies what that trust covers: every approval, every dollar of the budget, and every manuscript.
- **Fix:** authenticate at the proxy (Tailscale identity headers or basic/forward auth) and derive the operator from that identity server-side. Keep the per-form token only as CSRF protection. Record the authenticated identity in `actor_id`. See `HARDENING_STAGING.md` §2 and ADR proposal `ADR-0003`.
- **Docs contradicted:** `DECISIONS.md:11` "acceptance, canon mutation, and release review require explicit human decisions". A decision exists, but no human is identified.

#### AUD-002 — Staging proxy topology must neutralise the Host/Origin checks
- **Severity:** High · **Confidence:** Likely (the Caddyfile is not in the repo) · **CWE:** 346, 350 · **Leads:** K3.
- **Affected:** `server.py:79-82` accepts only `Host: 127.0.0.1:<port>`/`localhost:<port>`; `server.py:193-197` requires `Origin == "http://" + Host` when Origin is present.
- **Description:** A browser at `http://100.78.70.2:8767/` sends `Host: 100.78.70.2:8767`. Caddy's `reverse_proxy` preserves the incoming Host by default, so the app would answer 421. Staging works, so the proxy must rewrite Host. After that rewrite, every browser POST carries `Origin: http://100.78.70.2:8767`, which fails the comparison (403). Browser authoring works on staging, so the proxy must also strip or rewrite Origin. Under that configuration the app receives a loopback Host and no mismatching Origin on every request. Both defences are neutralised for the tailnet path. That includes DNS-rebinding requests that arrive with a foreign Host, unless the Caddy site block itself matches only the IP host.
- **Fix:** commit the Caddyfile. Make the proxy the enforcement point: a site address bound to the exact IP:port, rejection of other Host values, and an `Origin` allow-list at the proxy. Add authentication (AUD-001). Pass `X-Forwarded-Host` and have the app verify it against a configured public origin rather than accepting a rewritten Host.

#### AUD-003 — `kdp transition` reaches PREFLIGHT_PASSED / KDP_DRAFT_READY without build, candidate or approval
- **Severity:** Critical (a gate bypassable in normal use) · **Confidence:** Confirmed · **Actor:** anyone with CLI access, including the documented system administrator.
- **Affected:** `storage/service.py:354-380` gates only `PLANNED`; `cli/app.py:145-152`.
- **Reproduction:** `test_KDP_AUD_003_*`. The walk went EDITING → ASSET_READY → PREFLIGHT_PASSED → HUMAN_RELEASE_REVIEW → KDP_DRAFT_READY with **0 builds and 0 release candidates**.
- **Root cause:** transition legality is the only check. Release evidence lives in separate tables that the state machine never consults. The Workspace simply doesn't expose these edges.
- **Fix (patched):** `_require_release_evidence`. ASSET_READY requires an unblocked build. PREFLIGHT_PASSED requires a candidate with no blockers. KDP_DRAFT_READY requires an approved, unblocked candidate.
- **Docs contradicted:** `README.md:3` "human approval gates from concept through release preflight".

#### AUD-004 — Accepted chapters cannot be superseded; conditions and placeholders block release forever
- **Severity:** Critical (a core workflow cannot complete) · **Confidence:** Confirmed · **Who:** owner, KDP account.
- **Affected:** `chapter/service.py:284-320` (fixed destination; "exists" is always an error); `build/service.py:391-395` (conditions of included approvals are blockers); `release/service.py:108` (initial blockers are permanent); `workspace/actions.py:134-136` (a scripture condition is auto-added).
- **Reproduction:** `test_KDP_AUD_004_*`. The build is blocked by `scripture_placeholder` and `approval_condition`. The corrected revision is refused with "Accepted chapter destination exists with a conflicting hash".
- **Impact:** the documented workflow ("the reference must later be supplied and checked", PDF guide p. 5; "A remaining [SCRIPTURE NEEDED] placeholder continues to block release until a separate verified manuscript update resolves it", `review.py:257`) has no implementation. Pilot 1B is in exactly this state (`V1_0_PLATFORM_COMPLETE.md:32`).
- **Fix (patched):** `accept_chapter(..., supersede=True, supersede_reason=...)` and CLI `--supersede-reason`. The old version is archived under `12_archive/`, its row is marked `superseded`, and the change is audited. Builds then include only the replacement and its (condition-free) approval. A Workspace control is still needed (UX_RECOMMENDATIONS R3).

#### AUD-005 — Developmental editing is sent without the chapter while provenance lists it
- **Severity:** High · **Confidence:** Confirmed · **Leads:** K15.
- **Affected:** `editorial/service.py:190-199` passes the draft to `_planning_context` as if it were the card. The prompt variables are only title, ID and chapter number. `prompts/editorial/developmental-v1.0.md` has no content slot.
- **Evidence:** `evidence/KDP-AUD-005/request.json`. The manifest lists the draft asset; the rendered prompt is 214 characters with no chapter text.
- **Impact:** every developmental finding shown on review pages is uninformed. A real model returns generic advice or asks for the text. The Workspace offers it as a review aid before acceptance (C7).
- **Fix (patched):** `developmental-v1.1.md` includes `{{chapter_context}}`, built by the same `_chapter_authoring_context` helper the structured passes use, so the manifest equals what is sent. v1.0 is kept for provenance of historic jobs.

#### AUD-006 — Planning stages receive no concept, idea or prior-plan context
- **Severity:** High · **Confidence:** Confirmed.
- **Affected:** `planning/service.py:54-65`; all four `prompts/planning/*-v1.0.md` contain only title, ID and target reader, yet say "Use only supplied context". Workspace and CLI both pass `ContextManifest(inputs=[])` (`authoring.py:433`, `cli/app.py:195`).
- **Evidence:** `evidence/KDP-AUD-006/book_brief_prompt.txt`. The accepted positioning marker is absent from the book-brief request.
- **Impact:** the concept workflow (audience brief, seeds, enrichment, scoring, human concept approval) cannot influence positioning, brief, outline or chapter cards. Chapter cards never see the outline. The concept gate only blocks positioning; its content is never used.
- **Fix (patched):** `_accepted_planning_context` sends the idea note, the accepted concept brief and each accepted upstream planning artefact (integrity-checked). It records them in the manifest and renders `*-v1.1.md`.

#### AUD-007 — Provider-reported `usage.cost` overrides configured pricing
- **Severity:** High (cost-risk) · **Confidence:** Confirmed · **Actor:** a hostile or misconfigured OpenAI-compatible endpoint, or a gateway whose `cost` uses other units or credits.
- **Affected:** `providers/costs.py:114-116`; `openai_compatible.py:274-276`.
- **Evidence:** 100k input + 100k output tokens (configured-rate cost $1.125) were recorded as `estimated_cost 0.0`, `source provider_reported`.
- **Impact:** spent-to-date is under-reported, so the hard-stop allows more calls. Docs say settled cost uses configured rates (`ENVIRONMENTS.md:35`).
- **Fix (patched):** configured rates win. The provider figure is stored as a detail and may only raise the recorded cost.

#### AUD-009 — Profiles can forward any environment secret to any HTTPS host
- **Severity:** High (CVSS 7.1 `AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N`) · **Confidence:** Confirmed · **Leads:** K4, K9 · **CWE:** 522, 201.
- **Affected:** `providers/settings.py:476-496` (any env name; any HTTPS host); `openai_compatible.py:167-183`; `configuration.py:297-301` (`--connect` sends it too).
- **Evidence:** `evidence/KDP-AUD-009b/authorization_headers.json`. The cloud-credential canary was sent as a bearer token. `evidence/KDP-AUD-009/settings.json` shows both an unapproved host and `AWS_SECRET_ACCESS_KEY` accepted.
- **Who can create profiles:** CLI (`providers add-openai-compatible`), direct DB write, and any restored DB. Not the Workspace. The staging wrapper puts the provider key in the service environment, and any other variable in that environment is equally reachable.
- **Fix (patched):** remote hosts must be in `KDP_PROVIDER_HOST_ALLOWLIST` (default `api.openai.com`; loopback always allowed). Env names matching cloud, VCS, database or session secrets are refused. Validation also runs again at resolve time, so a tampered DB row is caught.

#### AUD-010 — Truncated / filtered / refused completions become acceptable chapters
- **Severity:** High · **Confidence:** Confirmed · **Leads:** K14.
- **Affected:** `generation/service.py:508-510` rejects only empty text. `finish_reason`, `refusal` and `incomplete_details` are recorded as diagnostics and then ignored. The review page does not display them.
- **Evidence:** accepted chapter text is `"…The hero stepped into the room and began to"`.
- **Fix (patched):** `_unusable_completion` rejects `length`, `content_filter`, `max_tokens`, `incomplete` and refusals after recording usage, never as a retry. The failure is audited as `generation.unusable_output_rejected`.

#### AUD-011 — Continuity rejects genuine "missing beat" findings after billing
- **Severity:** Medium · **Confidence:** Confirmed.
- **Affected:** `continuity/service.py:136-144` runs the "missing … outline/chapter/context" regex over the whole JSON, including the findings text.
- **Evidence:** the finding "The draft is missing the outline's second beat" was rejected as "required context is missing", with 1 billed usage event.
- **Fix (patched):** inside a valid, confirmed JSON contract only explicit requests for materials or refusal phrases invalidate the output. The same heuristic class exists in `editorial/service.py:40` (lower risk, noted).

#### AUD-012 — Canon baseline mutable on disk and fed to the model; approved proposals never apply
- **Severity:** High (invariant broken) · **Confidence:** Confirmed.
- **Affected:** `continuity/service.py:96-113` reads `06_canon/*.json` with no DB-anchored hash; `approve_canon_proposal` records `canon_mutated: False`; no apply path exists anywhere.
- **Evidence:** injected canon text was present in the continuity request; `doctor` was silent.
- **Impact:** "No canon mutation without an approved CanonProposal" is broken both ways. Canon changes without proposals (file edits). Approved proposals never change canon.
- **Fix (patched, detection):** `doctor` fails any non-empty canon file, since no legitimate writer exists. The real fix is an ADR plus a canon-apply service that writes canon only from accepted proposals and stores its hash in SQLite (ADR-0005 proposal).

#### AUD-013 — A failed generation can never be retried
- **Severity:** Medium · **Confidence:** Confirmed.
- **Affected:** `generation/service.py:342-349`. Identical inputs map to the same idempotency key, and a failed key raises forever.
- **Evidence:** after a mid-body reset, the operator's deliberate re-run failed with "idempotency key already exists with status failed".
- **Impact:** docs tell the operator to inspect and "retry deliberately" (`OPERATOR_WORKSPACE.md:34`); that is impossible without changing inputs.
- **Fix (patched):** an operator-initiated re-run creates a new job `…:attempt-N` with its own reservation and audit. There is still no automatic retry, so the AGENTS.md rule is preserved.

#### AUD-014 — Placeholder/unfinished-text detection is a single literal
- **Severity:** High (publishing-risk) · **Confidence:** Confirmed.
- **Affected:** `build/service.py:220`, `verification/service.py:23` — `\[SCRIPTURE NEEDED\]` only.
- **Evidence:** the build status was `built` for a chapter containing 5 placeholder variants plus `TODO`, `lorem ipsum` and `[TK]`.
- **Fix (patched):** a single broadened detector (bracket variants, NBSP/whitespace, suffixes) and an `unfinished_text` blocker class.

#### AUD-015 — Release approval allowed in POLICY_HOLD/RIGHTS_HOLD; no segregation of duties
- **Severity:** High · **Confidence:** Confirmed.
- **Affected:** `release/service.py:291-324` never reads the title state or who prepared the candidate.
- **Evidence:** title `POLICY_HOLD`, candidate `approved_for_manual_kdp_action`, one distinct actor for creation, 16 checks and approval.
- **Fix (patched):** hold and post-submission states are blockers, and the approver must differ from the creator and checklist reviewers (by recorded name; meaningful once AUD-001 is fixed). The state × action matrix shows holds also do not stop chapter acceptance or candidate creation.

#### AUD-016 — Chapter acceptance ignores title state and source chapter number
- **Severity:** High · **Confidence:** Confirmed.
- **Evidence:** a chapter-2 draft was accepted as `chapter-001.md` while the title was in `POLICY_HOLD` (CLI/service path; the Workspace derives the number from the filename).
- **Fix (patched):** the source filename number must equal `chapter_number`, and the title must be in DRAFTING.

#### AUD-017 — 303/405 responses lack security headers
Low · Code. `server.py:264-268, 285-289, 306-310, 325-333, 335-340` send only `Cache-Control`. Patched: `end_headers` adds the full set to every response.

#### AUD-018 — No per-connection socket timeout
Medium · Code. `BaseHTTPRequestHandler.timeout` is `None`, `ThreadingHTTPServer` spawns an unbounded number of threads, and `rfile.read(size)` trusts `Content-Length`. Slow or idle connections pin threads indefinitely. Patched: `timeout = 30`. Recommended in addition: a connection cap at the proxy.

#### AUD-019 — Unhandled DB errors drop the connection with no response
Medium · Confirmed. The concurrency run produced raw `sqlite3.OperationalError: database is locked` in 2 of 12 requests. In the server, only `ValueError/OSError/RuntimeError` are caught, so the operator sees a dropped connection after a possibly billed call. Patched: a catch-all in `handle_one_request` returns a 503 page and logs the traceback. A 15 s busy timeout is also set.

#### AUD-020 — Every page recomputes every title
Medium (performance) · Confirmed by measurement (`evidence/perf/perf.json`). Home snapshot times: 0.31 s at 1 title, 1.24 s at 5, 4.30 s at 15 (10 chapters × 3,000 words each). The profile (`profile_inspect_workspace.txt`) shows ~80 SQL statements and ~170 SHA-256 file hashes per title, a new engine per call, and `init_db` (DDL/ALTER checks) inside read paths. Design: cache hashes by `(path, mtime, size)`, compute the title report once per request, and move `init_db` out of `session_scope`.

#### AUD-021 — Audit log is mutable; app deletes audit rows on rollback
- **Severity:** High · **Confidence:** Confirmed · **Leads:** K5.
- **Affected:** `storage/audit.py` (application-level only); `storage/service.py:105,149` delete `AuditEventRow` in compensation paths.
- **Evidence:** UPDATE and DELETE succeeded, and `doctor` reported nothing.
- **Fix (patched):** SQLite `BEFORE UPDATE/DELETE` triggers raise. Compensation appends `*.create.rolled_back` instead of deleting, and `doctor` checks that the triggers exist.
- **Follow-up:** a hash chain for tamper evidence against a DB-file attacker (ADR-0004 proposal). The "77 references rebased with audited path rebase" claim cannot be reproduced from the repo (no script); `kdp relocate` now provides one (AUD-027).

#### AUD-022 — Billed response with malformed usage loses the usage record
Medium · Confirmed. `usage.prompt_tokens = -5` raised a pydantic `ValidationError` inside the adapter. That happens after the provider billed and before usage is recorded, so 1 provider call left 0 usage events and the reservation was marked "uncertain". Patched: tolerant integer parsing (invalid → `None`, recorded as unknown). A billed 200 always records usage.

#### AUD-023 — Provider response size unbounded
Medium · Confirmed. A 48 MB body was read entirely and stored as a 50,331,648-byte chapter draft. Patched: the response is streamed with a 4 MiB cap.

#### AUD-025 — Output is Markdown only; KDP metadata, cover, keywords, categories, pricing not captured
- **Severity:** High (publishing) · **Confidence:** Confirmed (code) · **Leads:** K22.
- KDP accepts EPUB, DOCX and KPF for eBooks, and PDF/DOC/DOCX/RTF/HTML/TXT for paperbacks (PDF/X-1a preferred when bleed is used) *(index-extract, [G200634390](https://kdp.amazon.com/en_US/help/topic/G200634390), [G202145060](https://kdp.amazon.com/en_US/help/topic/G202145060), retrieved 2026-09-29)*. Markdown is not accepted. The metadata checklist records a free-text "complete" and never captures author, description, up to 7 keywords or 3 categories *(index-extract, [G201298500](https://kdp.amazon.com/en_US/help/topic/G201298500), [G200652170](https://kdp.amazon.com/en_US/help/topic/G200652170))*. There is no cover handling at all, and `prompts/packaging/` is empty.
- Nothing in the output claims to be "KDP-ready". The packet says "Verify current requirements against official KDP documentation".
- See the §7 KDP table and `DESIGN_EXPORT.md`.

#### AUD-026 — Atomic writes without fsync
Low · Code. `storage/files.py:71-100`: `os.replace` without an fsync of the file or its directory, and DB commits reference hashes of files that may not be durable after power loss. `shutil.copy2` on acceptance is not atomic. Patched for `write_text`/`write_json`. `copy2` is left as a follow-up.

#### AUD-027 — Absolute paths in DB; restored copy fails every check; no relocate tool
High · Confirmed · Leads K16. Restoring to another directory produced 12 `FAIL` asset checks. The documented Windows → Linux migration used an unrecorded procedure. Patched: `kdp relocate --from OLD [--dry-run]` rebases POSIX and Windows prefixes across assets, builds, findings and proposals. It verifies every hash before committing and records one audit event. `doctor` now points to it.

#### AUD-028 — `target_reader` is never set
Medium · Code. `TitleRow.target_reader` has no writer (`grep` finds only readers), so every planning and drafting prompt says "Target reader: unspecified", including the youth-book pilot. The Workspace's "Who is the book for?" goes only into the idea note, which (before the AUD-006 patch) never reached planning. Fix: set `target_reader` from the create-book form and a CLI option.

#### AUD-029 — Prompt template file hash not in provenance
Medium · Confirmed. An edited `outline-v1.0.md` is recorded as outline v1.0. Patched: `RenderedPrompt.template_sha256` is stored in the new `provenance.prompt_template_sha256` column (additive migration).

#### AUD-030 — Stray `.md` in `prompts/` disables all generation
Low · Confirmed. Adding `prompts/README.md` makes `PromptRegistryError` fire on every path. Patched: `README.md` and `_*.md` are skipped.

#### AUD-031 — AI disclosure under-counts
- **Severity:** High (publishing-risk) · **Confidence:** Confirmed.
- **Affected:** `workspace/authoring.py:536-547` always labels manual edits `AI_ASSISTED` and `creator_type="human"`; `release/service.py:198` counts only `creator_type == "ai"`.
- **Evidence:** a one-character edit of an AI chapter gave `ai_asset_count: 0` in the release summary.
- **KDP definitions** *(index-extract, [Content Guidelines G200672390](https://kdp.amazon.com/en_US/help/topic/G200672390), retrieved 2026-09-29)*: AI-generated content ("text, images, or translations created by an AI-based tool") must be disclosed. AI-assisted means "content created by you that was edited, refined, error-checked, or otherwise improved using AI-based tools". Under these definitions, an AI draft edited by a human is AI-generated, not AI-assisted.
- **Fix (patched):** the lineage is preserved as `AI_GENERATED_HUMAN_EDITED` / `creator_type="ai+human"`, and the summary counts it. Not legal advice. The human still confirms the disclosure.

#### AUD-032 — Build silently drops every line equal to the chapter heading
Medium · Confirmed. `build/service.py:408-409` filters all lines equal to the heading, so a repeated `# Chapter One` inside the body vanished. Patched: only the first occurrence is removed.

#### AUD-033 — `/healthz` never touches DB or disk
Low · Code. `server.py:100-102` returns `ok` even when the DB is missing, locked or corrupt. Design: add `/readyz`, which opens the DB read-only, runs `PRAGMA quick_check`, and checks free disk space.

#### AUD-034 — No access log
Medium · Code · K6. `log_message` returns without writing anything, so there is no record of who called what. Patched: a path-only access log (no query strings or bodies) via `logging`. With AUD-001 fixed, this becomes an attributable request log.

#### AUD-035 — CLI generation lacks Workspace controls
Medium · Code · K8/K10. The CLI generation commands need no cost acknowledgement, no priced profile and no budget. A project without a budget is uncapped (documented). Design: move `_require_generation_controls` into `GenerationService` with an explicit `--allow-unbudgeted` override that is audited.

#### AUD-036 — Editor limits
Medium · Code. The source is capped at 100,000 bytes (`authoring.py:478`, undocumented; the review page allows 1 MB). The body is capped at 200,000 URL-encoded bytes (`server.py:233`), about 66 KB for non-ASCII-heavy text. `_required` strips leading and trailing whitespace from content. A 413 returns a generic page, losing the operator's edit. Design in `UX_RECOMMENDATIONS.md` R6.

#### AUD-037 — `build matter-add` copies any readable file
Low · Code. `build/service.py:231-247` reads `source_path` anywhere on disk (e.g. `~/.config/kdp-workspace/openai.key`) into project artefacts and, once accepted, into the manuscript. The CLI operator is trusted, but this is a secret-hygiene hazard. Design: restrict matter sources to the title workspace.

#### AUD-038 — No CI, lint, type gates or lockfile; low mutation score
- **Severity:** Medium · **Confidence:** Confirmed.
- **Coverage and mutation:** 77% line+branch coverage, with `cli/app.py` at 43%. The mutation score is **4/19**:
  - State machine: 6 of 9 transition-table mutants survive (e.g. `ASSET_READY → KDP_DRAFT_READY`).
  - Budget gate: 9 of 10 survive (e.g. dropping `reserved` from the projection, the `>1.5×` monthly limit, the month filter).
- **Static analysis:** `mypy` reports 108 errors (295 with `--strict`); ruff with the proposed rule set reports 2,202 findings, mostly E501; `radon` places `inspect_title` at CC **316** and `inspect_review` at 91.
- **Tooling:** no lockfile; `pip-audit` finds no vulnerable runtime dependencies (the only hit is `pip` itself, PYSEC-2026-3721).
- **Plan:** see `REFACTOR_PLAN.md` and the CI design.

#### AUD-039 — Documentation contradictions on material facts
Medium · Confirmed. See §7 and `recon/claims.csv` (85 claims: 46 TRUE, 27 PARTIAL, 9 FALSE, 3 UNTESTABLE). Examples:
- Pricing: "configured in both databases" (`ENVIRONMENTS.md:35`) vs "intentionally unset" (`V1_0…:33`).
- Staging: runs tag `7b5feb6`, yet the docs describe browser book creation there, which was added only in `91c48ad`.
- Workspace: "does not write operational state directly" (`OPERATOR_WORKSPACE.md:5`), but `authoring.py` writes rows directly.
- Canon: "Canon changes require proposal review" (V1.0), contradicted by AUD-012.

#### AUD-040 — `doctor` misses manifest, canon and approval tampering
High · Confirmed. It reported **0** problems after a build manifest was deleted, a canon file edited and an approval hash forged. It checks only asset files. Patched: checks for build manifests, approval ↔ asset hash, canon, audit triggers and out-of-root paths.

#### AUD-041 — No schema version
Medium · Confirmed. `user_version` is 0 and there is no migrations table. Older code opens a newer DB silently. Patched: `SCHEMA_VERSION = 2`, and a newer DB is refused. The v0.1 → HEAD upgrade works (positive control).

#### AUD-042 — Foreign keys declared but not enforced
Medium · Confirmed. `PRAGMA foreign_keys = 0`. Enabling it breaks 38 existing tests because the ORM inserts `approvals` before `assets` (no `relationship()` ordering), so the constraints have never been exercised. Patched:
- `foreign_keys=ON` and `busy_timeout=15000`;
- SQLAlchemy's documented explicit-BEGIN pattern, with `defer_foreign_keys` so constraints are checked at commit.

After the patch, all 122 original tests pass.

#### AUD-043 — CRLF vs LF produces different content hashes
Medium · Confirmed · K19. `write_text(newline="")` does no normalisation, so the same chapter hashes differently on a Windows `core.autocrlf` checkout. Patched: CRLF and CR are normalised to LF at write. Other `open()` calls already pass `encoding="utf-8"`.

#### AUD-044 — AI revisions cannot be accepted in the browser
- **Severity:** High · **Confidence:** Confirmed (new, found while patching).
- **Affected:** `review.py:164`, `chapters/service.py:19`, `authoring.py:514` and `inspection/service.py:230,242` match `chapter.(draft|revision).N`. The generator names revisions `chapter.revise.N-JOB….md`.
- **Evidence:** the dossier blocker reads "The chapter number cannot be determined from the artefact path"; `chapter_status` omits the revision.
- **Fix (patched):** all regexes accept `revise`.

#### AUD-045 — Staging details in repository docs
Low. `ENVIRONMENTS.md` publishes the tailnet IP, host name, Unix account, service names and key path. That is harmless while the tailnet is private, but it gives an attacker a map. Keep it in an ops note outside the repo if the repo is or becomes public.

#### AUD-046 — Wheel ships no prompts
Low · Confirmed. The wheel contains only Python code plus two static files (`evidence/tools/wheel_nonpy.txt`), while the registry and doctor read `<root>/prompts`. Deployment correctness therefore depends on a full checkout, which is how staging is deployed. Package the prompts, or document that a checkout is mandatory.

#### AUD-047 — Audience safety and originality have no enforced gate
Medium · Code. Youth appropriateness exists only as prompt wording and concept warnings. There is no content-safety pass, no PII/real-person check and no n-gram or shingle originality check against supplied sources; a human would notice regurgitated text only by reading. Design: a deterministic pre-release originality gate (shingle overlap against `02_sources/`) and a safety pass whose findings are blockers (`SECURITY_BACKLOG.md` items).

#### AUD-048 — Continuity "fail" and open critical findings do not block acceptance
Medium · Code. `status: "fail"` becomes an "open review" finding, and the asset dossier lists findings but `can_decide` ignores them. Design: unresolved `critical` or continuity-`fail` findings should be blockers that require an explicit waiver with a rationale.

#### AUD-049 — UX issues
Low · Confirmed. Details in `UX_RECOMMENDATIONS.md` and `evidence/ui/`: a separate "Operator name" field on almost every form (about 15 on one title page); up to 16 raw IDs per page; "hard budget: True"; horizontal overflow at 768 px on every page and at 390 px in the editor; the double-submit guard covers generation forms only.

## 5. Seeded leads K1–K23

| Lead | Verdict | Finding / evidence |
|---|---|---|
| K1 no auth, global CSRF token | CONFIRMED (code) | AUD-001 |
| K2 free-text operator identity | CONFIRMED | AUD-001, AUD-015 (one name everywhere) |
| K3 proxy Host/Origin | PARTIAL (analytical, not lab-reproduced) | AUD-002 |
| K4 secret exfiltration via profile | CONFIRMED | AUD-009 |
| K5 app-level append-only | CONFIRMED (+ app itself deletes audit rows) | AUD-021 |
| K6 access logging disabled | CONFIRMED | AUD-034 |
| K7 server hardening | CONFIRMED (code) | AUD-017/018/019/020 |
| K8 two entry points | CONFIRMED | AUD-003, AUD-016, AUD-035; `recon/dataflow-and-trust.md` table |
| K9 secrets hygiene | PARTIAL — keys never persisted (held); profile egress broken (AUD-009); free text unscreened | POS tests |
| K10 no default cap | CONFIRMED (documented) | AUD-035 |
| K11 reservation TOCTOU | **REFUTED** (serialized by SQLite writer lock taken at job INSERT flush; fragile — depends on flush order; contention yields raw lock errors) | POS-K11, AUD-019 |
| K12 money handling | PARTIAL — provider cost trusted (AUD-007); floats acceptable at these magnitudes; month bucketing UTC and consistent; `provider_outcome_unknown` reservations count until month end, then silently drop out of `reserved` | AUD-007 |
| K13 lost usage | CONFIRMED for malformed usage (AUD-022); crash between response and commit leaves a `running` job + `reserved` reservation with no recovery command (analytical) | AUD-022 |
| K14 adapter hazards | CONFIRMED — unbounded body (AUD-023), finish reasons ignored (AUD-010); redirects not followed (held); no retry/backoff (held, by design); `trust_env=True` means `HTTPS_PROXY` in the service environment sees the key (documented risk) | |
| K15 manifest ≠ request | CONFIRMED | AUD-005, AUD-006 |
| K16 absolute paths | CONFIRMED | AUD-027 |
| K17 SQLite ↔ files consistency | CONFIRMED gaps — no fsync (AUD-026), FKs off (AUD-042); WAL not enabled (rollback journal) | |
| K18 ad-hoc schema evolution | PARTIAL — v0.1 → HEAD upgrade works; no version marker (AUD-041) | |
| K19 cross-OS determinism | CONFIRMED | AUD-043 |
| K20 chapter vs chapters | REFUTED as duplication: `chapter/` = single-chapter lifecycle, `chapters/` = queue/summaries; both reachable; naming is confusing (REFACTOR_PLAN step 6) | |
| K21 large modules, no gates | CONFIRMED | AUD-038 |
| K22 KDP fitness gap | CONFIRMED | AUD-025, §7 |
| K23 governance docs vs reality | CONFIRMED | AUD-039, §7 |

## 6. Invariant verdicts (AGENTS.md "Mandatory design principles")

| Principle | Verdict | Entry points examined | Tests |
|---|---|---|---|
| SQLite is authoritative | HOLDS-WITH-GAPS | canon files, prompts, path storage | AUD-012, AUD-029, AUD-027 |
| AI output experimental until accepted | HOLDS | generation writes experimental only; acceptance copies | state matrix |
| No canon mutation without approved CanonProposal | **BROKEN** | disk edits consumed; no apply path | AUD-012 |
| No accepted AI asset without provenance | HOLDS | accept_chapter/planning/concept require provenance | code |
| Every workflow state mutation auditable | **BROKEN** | mutable audit table; compensation deletes | AUD-021 |
| Providers replaceable | HOLDS | adapter isolation | code |
| Deterministic tasks use deterministic code | HOLDS-WITH-GAPS | context confirmation is model self-report | AUD-005 |
| Policy/rights/quality/approval failures never auto-retried | HOLDS | no retry anywhere (patched manual retry is operator-initiated) | AUD-013 |
| Official KDP docs outrank other sources | HOLDS-WITH-GAPS | no rule cites a source/date; checklist is free text | §7 |
| AI workers never receive KDP credentials etc. | HOLDS-WITH-GAPS | no such fields; free-text fields forwarded unscreened | dataflow table |
| Final KDP publication human-controlled | HOLDS for upload; **BROKEN** for the state that represents it (KDP_DRAFT_READY reachable without approval) | AUD-003 |
| Backwards compatibility | HOLDS | v0.1 DB upgrade | POS test |
| Human approval gates (DECISIONS.md) | **BROKEN** | CLI transition; hold states; identity | AUD-001/003/015 |

State × action matrix: `recon/state-action-matrix.md`. Holds and post-submission states block generation and builds but not chapter acceptance or release-candidate creation. `KDP_EXCEPTION` and `UPDATE_ASSESSMENT` are dead ends with no outgoing edges and no documented recovery. A passed preflight is not invalidated by later edits: there is no link from the manuscript back to the title state.

## 7. Documentation vs reality, and KDP requirement coverage

Material documentation claims (full list: `recon/claims.csv`):

| Claim | Source | Verdict |
|---|---|---|
| "human approval gates from concept through release preflight" | README.md:3 | FALSE (AUD-003) |
| "No canon mutation … without an approved CanonProposal" / "Canon changes require proposal review" | AGENTS.md; V1_0:20 | FALSE (AUD-012) |
| "settled cost uses provider token usage and the configured rates" | ENVIRONMENTS.md:35 | FALSE (AUD-007) |
| "the reference must later be supplied and checked by a person" | PDF guide p5 | FALSE (AUD-004) |
| "Use only supplied context" (planning prompts) | prompts/planning | FALSE (AUD-006) |
| Pilot pricing configured vs "intentionally unset" | ENVIRONMENTS:35 vs V1_0:33 | CONTRADICTORY |
| Browser book creation on staging | README:49, ENVIRONMENTS:43 | UNSUPPORTED by the deployment record (tag predates the feature) |
| "77 references rebased … audited path rebase" | ENVIRONMENTS:11 | UNTESTABLE (no tooling in repo) |
| "rejects requests from a different origin" | OPERATOR_WORKSPACE:65 | PARTIAL (absent Origin accepted) |
| "kdp doctor is read-only" | README:91 | TRUE (inspect paths via `session_scope` run DDL — PARTIAL) |
| 122 tests, 45 commits, Sprint 1–16 features present | brief/ROADMAP | TRUE |

### KDP requirement coverage

Sources are *index-extracts* of official KDP help pages, retrieved 2026-09-29; the live pages could not be fetched here, so re-verify before relying on them.

| Requirement | Official source | Pipeline |
|---|---|---|
| eBook manuscript format: EPUB, DOCX, KPF (MOBI withdrawn for fixed layout from 2025-03-18) | [G200634390](https://kdp.amazon.com/en_US/help/topic/G200634390) | (d) ignored — Markdown only |
| Paperback interior: PDF (required with bleed; PDF/X-1a preferred), or DOC/DOCX/RTF/HTML/TXT; 300 DPI images; embedded fonts | [G202145060](https://kdp.amazon.com/en_US/help/topic/G202145060), [G201857950](https://kdp.amazon.com/en_US/help/topic/G201857950) | (d) ignored |
| Cover | [G6GTK3T3NUHKLEFX](https://kdp.amazon.com/en_US/help/topic/G6GTK3T3NUHKLEFX) | (d) ignored (`08_art/` unused) |
| Title/subtitle/author/series must match cover | [G201097560](https://kdp.amazon.com/en_US/help/topic/G201097560) | (c) checklist free text; author not captured |
| Up to 7 keywords; avoid subjective/time-sensitive/misleading | [G201298500](https://kdp.amazon.com/en_US/help/topic/G201298500) | (c) checklist only; no packaging prompts |
| Up to 3 categories, must be relevant | [G200652170](https://kdp.amazon.com/en_US/help/topic/G200652170) | (c) checklist only |
| AI-generated content must be disclosed; AI-assisted need not | [G200672390](https://kdp.amazon.com/en_US/help/topic/G200672390) | (a)+(c) captured as provenance + checklist statement; **under-counted** (AUD-031) |
| Public-domain content rules | [G200743940](https://kdp.amazon.com/en_US/help/topic/G200743940) | (d) not modelled (relevant to KJV use) |
| Content quality / "disappointing content" | [G200952510](https://kdp.amazon.com/en_US/help/topic/G200952510) | (c) editorial passes advisory only |
| Title-creation volume limits | [G201857950](https://kdp.amazon.com/en_US/help/topic/G201857950) (index text ambiguous; re-verify) | (d) no friction on batch creation; queue capped at 10 chapters, not titles |
| Pricing/royalty/territories/rights declaration | KDP bookshelf | (c) `rights_and_territories` checklist key only |

**Scripture licensing** (from secondary sources; confirm with the publishers):

| Translation | Permission terms |
|---|---|
| NIV (Biblica) | Up to 500 verses without written permission, if the verses are under 25% of the work and not a complete book; a notice is required. |
| ESV (Crossway) | Similar 500-verse / 25% / half-a-book limits; not for commentaries. |
| KJV | Crown-patent rights in the United Kingdom (administered by Cambridge University Press); public domain elsewhere. |

([Crossway](https://www.crossway.org/permissions/), [Biblica](https://www.biblica.com/resources/bible-faqs/do-i-have-to-notify-biblica-to-use-a-bible-verse-from-the-niv/), [Blue Letter Bible version copyrights](https://www.blueletterbible.org/versions.cfm))

The pipeline records a free-text `source_policy` per verification item. It does not count verses, record the translation, or generate the required copyright notice. That is jurisdiction- and translation-dependent and should be modelled explicitly (SECURITY_BACKLOG B-17).

## 8. Quality dashboard

| Metric | Value | Evidence |
|---|---|---|
| LOC (src) | 9,831 (8,825 per bandit) | `wc` |
| Tests | 122 passed, 1 skipped (47 s); identical under random order, `-W error`, `-X dev` | `evidence/tools/pytest_*.txt` |
| Coverage (line+branch) | 77% (cli 43%, workspace/authoring 57%, server 64%) | `coverage_report.txt` |
| Mutation score (state machine + budget gate) | 4/19 = 21% | `mutation.txt` |
| mypy | 108 errors default; 295 `--strict` | `mypy_*.txt` |
| ruff (proposed set) | 2,202 (1,831 E501; 83 B008; 72 B904; 21 C901) | `ruff_stats.txt` |
| Worst complexity | `inspect_title` 316, `inspect_review` 91, `_attention` 50, `doctor` 48, `OpenAICompatibleProvider.generate` 45, `GenerationService.generate` 41 | `radon_cc.txt` |
| Maintainability index C | `inspection/service.py` 0.00, `workspace/render.py` 0.00, `cli/app.py` 5.5, `release/service.py` 6.1 | `radon_mi_worst.txt` |
| bandit | 0 real issues (13 Low / 1 Medium, all false positives: pass-type strings, a fixed-dict ALTER) | `bandit.txt` |
| Secrets in history | 0 (gitleaks, trufflehog; 45 commits, all refs) | `gitleaks.txt`, `trufflehog.stderr` |
| Dependencies | pip-audit: no runtime vulns; licences MIT/BSD | `pip_audit.txt` |
| Accessibility (axe WCAG 2.0/2.1/2.2 A+AA + best-practice) | **0 violations** on 8 pages incl. dark theme | `evidence/ui/a11y_report.json` |
| Responsive | horizontal overflow at 768 px (all pages), 390 px (editor) | same |

Hot list (ranked for maintainability risk): `inspection/service.py::inspect_title`, `workspace/review.py::inspect_review`, `workspace/render.py` (string-built HTML, MI 0), `cli/app.py` (1,041 lines, 43% covered), `generation/service.py::generate`, `providers/openai_compatible.py::generate`, `chapter/service.py::accept_chapter`, `planning/acceptance.py::accept_planning_artifact`, `providers/costs.py::evaluate_and_reserve`, `workspace/actions.py::run_review_decision`, `workspace/render.py::_attention`, `inspection/service.py::doctor`, `workspace/authoring.py::create_manual_revision`, `release/service.py::_blockers`, `build/service.py::build_manuscript`.

## 9. Unconfirmed hypotheses and areas not reached

- Lab reproduction of AUD-001/002: DNS rebinding through the proxy, absent-Origin acceptance, and HEAD/GET divergence (withheld, see exclusions).
- Kill-point crash matrix (process kill between file write and commit): analysed from code, not executed. Every write path writes the file first and deletes it on exception, but a `SIGKILL` leaves orphan files or `.tmp` files (no sweeper) and `running` jobs (no recovery).
- Windows-specific behaviour (reserved names, 260-character paths, drive-letter case) was reasoned about but not run. The relocate patch handles Windows prefixes (unit-level only).
- Real-browser XSS fuzzing of every field; escaping reviewed statically.
- Title-volume limits on KDP (the index text was ambiguous).
- Provider-side data retention and training settings: not modelled in profiles. This needs a documented decision per provider.

## 10. Remediation roadmap

**Before the next paid generation (S):** apply the AUD-005/006/010/022/023/007 patches. Set hard-stop budgets on every project. Stop using developmental findings until patched. Restrict staging paid generation to the owner's device via Tailscale ACL.

**Before a second operator (M):** AUD-001 (proxy identity → operator), AUD-002 (committed Caddyfile, Origin allow-list), AUD-015 (segregation of duties), AUD-021 (triggers + hash chain), AUD-034 (access log), AUD-018/019.

**Before first KDP publication (L):** AUD-004 (supersede, including a Workspace control), AUD-014, AUD-031, AUD-025 (DOCX/EPUB export and metadata capture per DESIGN_EXPORT.md), AUD-047 (originality and safety gates), Scripture licence modelling, AUD-003 transition gates.

**Hardening backlog:** AUD-012 canon apply service and ADR; AUD-020 performance; AUD-027/040/041/042/043 durability; AUD-038 CI/lint/types/mutation; AUD-035 CLI parity; AUD-036 editor; AUD-044 (patched); documentation fixes (AUD-039).

## 11. Positive findings (preserve these)

- **Output encoding:** every interpolation in `render.py` passes through `html.escape(quote=True)` or `quote()`. The CSP (`script-src 'self'`) was observed blocking inline script in Chromium.
- **Key handling:** keys are never persisted. Provider error identifiers are filtered to identifier-like strings, and an Authorization echo in error bodies never reached jobs or audit rows.
- **Offline check:** `providers check` without `--connect` makes no socket connection. Redirects are not followed.
- **Review freshness:** the `review_hash` rejects stale decision forms, and consequence text is precise and honest.
- **Idempotent acceptance:** acceptance is idempotent and never overwrites differing content.
- **Deterministic builds:** builds are byte-deterministic on the same OS.
- **Cost estimates:** estimates use UTF-8 bytes as a conservative token bound. Hard-stop blocks unpriced models. Transport timeouts are recorded as `provider_outcome_unknown` rather than failures.
- **Upgrade path:** a v0.1 database upgrades in place.
- **Repository hygiene:** no secrets in history, `projects/*` ignored from the first commit, and no vulnerable runtime dependencies.
- **Accessibility:** zero axe violations, in both themes.
- **Workflow:** no automatic retry anywhere, and queue controls never draft.
