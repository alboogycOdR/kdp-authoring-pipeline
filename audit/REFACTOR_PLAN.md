# Refactor plan (test-protected, stepwise)

Principles: every step lands with the existing 122 tests + the audit suite green; no behaviour change unless the step says so; each step is one PR. Size: S ≤ 1 day, M ≤ 3 days, L ≤ 2 weeks.

## Step 0 — Gates first (S)
1. Add CI (`.github/workflows/ci.yml`): Python 3.12 and 3.13; `pip install -e .[dev]`; `pytest -q`; `bash audit/run_audit.sh` against the patched tree; `pip-audit`; `gitleaks detect`.
2. Add `ruff` with a *sensible* config (below) and a **ratchet**: CI fails only if the count grows.
3. Add `mypy` (non-strict) with a baseline file; ratchet down per step.
4. Pin with a lockfile (`uv lock` or `pip-tools`), keep floor pins in `pyproject.toml`.

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "W", "B", "S", "UP", "SIM", "C90", "PLR0911", "PLR0912", "PLR0915"]
ignore = ["E501", "B008", "S101"]   # long lines tolerated during refactor; typer defaults are idiomatic
[tool.ruff.lint.mccabe]
max-complexity = 20
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S", "PLR"]
```

## Step 1 — Raise mutation score on safety-critical modules (M)
Table-driven tests for `core/state_machine.py` (every edge allowed/denied — kills all 6 surviving mutants), property tests (Hypothesis) for `providers/costs.py` (reserve/settle sequences never exceed cap; `projected = spent + reserved + estimate`; month filter), and for placeholder detection. Target ≥ 80% mutation score on `state_machine`, `costs`, `release`, `verification`, acceptance functions.

## Step 2 — Schema migrations (M)
Replace `create_all` + ad-hoc `ALTER TABLE` with Alembic (or a 60-line numbered-migration runner using `PRAGMA user_version`, already introduced by the patch). Each migration idempotent and tested from every tagged schema (`v0.1`, `v0.2`, `v0.3`, `v1.0`, HEAD). Add `kdp db status`.

## Step 3 — Split `cli/app.py` (M)
One module per sub-app (`cli/providers.py`, `cli/release.py`, …) registered in `cli/__init__.py`. Move shared error handling into a decorator that maps `ValueError`→exit 2, `OSError`→exit 3, others→exit 1 with a stable message. Add `--json` consistently. No command renames.

## Step 4 — Inspection and review (L)
`inspect_title` (CC 316) → a `TitleReadModel` built once per request from a few set-based queries; per-section pure functions (`planning_section(model)`, `release_section(model)`); file hashes via a `(path, size, mtime_ns)` cache. `inspect_review` (CC 91) → one function per kind. Targets: home page ≤ 150 ms at 20 titles; CC ≤ 20 everywhere.

## Step 5 — Templates with auto-escaping (M)
Replace string-built HTML in `workspace/render.py` with Jinja2 (`autoescape=True`) templates; keep URLs built with `quote`; snapshot tests compare rendered HTML before/after for every page state. Removes the "every interpolation must remember `_e()`" hazard (currently held by discipline).

## Step 6 — Naming and layering (S)
Rename `chapter/` → `chapter_lifecycle/`, `chapters/` → `chapter_queue/` (K20). Enforce layering with `import-linter`: `cli`, `workspace` → services → `storage`/`providers`; services must not import `workspace`. Move `create_manual_revision`'s direct row writes into a `revisions` service.

## Step 7 — Configuration consolidation (S)
One `Settings` object (pydantic-settings) for root, port, host allow-list, provider host allow-list, timeouts, log level; read once at startup; injected. `utcnow()`/`new_id()` injectable for deterministic tests.

## Step 8 — Real auth layer (M, after ADR-0003)
Trusted-proxy identity middleware; per-request `Actor`; remove operator form fields; roles `author`, `reviewer`, `admin`; SoD rules expressed over roles. Sessions not needed when identity comes from Tailscale/forward-auth.

## Step 9 — Transactions around file + DB writes (M)
A `unit_of_work(root)` helper: write files to `.staging/`, commit DB, then atomic rename into place, with a recovery sweep on startup (orphans, `running` jobs past timeout → `provider_outcome_unknown`). Replaces the scattered try/unlink compensation code.
