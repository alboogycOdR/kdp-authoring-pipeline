# Audit workspace

Everything produced by the full-spectrum audit of `alboogycOdR/kdp-authoring-pipeline` at `91c48ad`. **Start with [REPORT.md](REPORT.md).** No file outside `audit/` was modified; proposed fixes are patches, not applied.

## Layout

| Path | Content |
|---|---|
| `REPORT.md` | Findings, chains, lead resolutions, invariant verdicts, KDP coverage, roadmap |
| `SECURITY_BACKLOG.md` | Findings as actionable issues with acceptance criteria and the test that must pass |
| `REFACTOR_PLAN.md`, `UX_RECOMMENDATIONS.md`, `DESIGN_EXPORT.md`, `HARDENING_STAGING.md` | Designs (proposals only) |
| `AGENTS_PROPOSED.md`, `adr-proposals/` | Governance proposals |
| `tests/` | Exploit/regression suite (incl. the C1 forged-approval chain, `test_ws_b_workspace.py`); `test_KDP_AUD_###_*` fail on baseline, `test_POS_*` are positive controls |
| `patches/` | `ALL-KDP-AUD-fixes.patch` (verified on a clean checkout) and per-area splits |
| `lab/` | Mock provider, fixtures, data generator, mutation harness, state × action harness, browser a11y scanner |
| `recon/` | Route table, CLI tree, data flow & trust boundaries, state × action matrix, `claims.csv` |
| `evidence/` | Per-finding evidence (`KDP-AUD-###/`), mock request logs, tool outputs, UI screenshots/axe report, perf |
| `LOG.md` | Timestamped log of commands and decisions |

## Reproduce

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
bash audit/run_audit.sh                      # baseline: 31 failed (findings), 10 passed (controls)

git worktree add --detach ../kdp-patched 91c48ad
git -C ../kdp-patched apply "$PWD/audit/patches/ALL-KDP-AUD-fixes.patch"
(cd ../kdp-patched && PYTHONPATH=src python -m pytest -q tests)   # 122 passed, 1 skipped
KDP_AUDIT_TARGET=../kdp-patched bash audit/run_audit.sh           # 41 passed
```

Lab rules honoured: throw-away roots only; mock provider bound to 127.0.0.1; canary keys are obviously fake (`sk-CANARY-…`, `canary-cloud-secret-…`); no request to any real LLM API, KDP/Amazon account, or the staging host. Official KDP help pages were blocked by the sandbox egress proxy, so KDP policy facts come from their search-index extracts and are marked as such.

Scope note: chain C1 (forged human approval) is reproduced end-to-end over HTTP in `lab/c1_chain.py`. The staging proxy topology (AUD-002) is the one WS-B item resolved analytically rather than stood up (see REPORT §1).
