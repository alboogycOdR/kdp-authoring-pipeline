"""Tiny, dependency-free mutation harness (mutmut 3 needs a config rewrite of this repo).

Applies one textual mutant at a time to a copy of the source tree, runs the named tests,
and reports killed/survived. Usage: python audit/lab/mini_mutation.py > audit/evidence/tools/mutation.txt
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGETS = {
    "src/kdp_pipeline/core/state_machine.py": (["tests/test_state_machine.py", "tests/test_foundation_flow.py",
                                                  "tests/integration/test_planning_pipeline.py"], [
        ("TitleState.IDEA: {TitleState.VALIDATED}", "TitleState.IDEA: {TitleState.VALIDATED, TitleState.DRAFTING}"),
        ("TitleState.ASSET_READY: {TitleState.PREFLIGHT_PASSED, TitleState.PREFLIGHT_FAILED}", "TitleState.ASSET_READY: {TitleState.PREFLIGHT_PASSED, TitleState.PREFLIGHT_FAILED, TitleState.KDP_DRAFT_READY}"),
        ("TitleState.PREFLIGHT_PASSED: {TitleState.HUMAN_RELEASE_REVIEW}", "TitleState.PREFLIGHT_PASSED: {TitleState.HUMAN_RELEASE_REVIEW, TitleState.LIVE}"),
        ("TitleState.KDP_DRAFT_READY: {TitleState.HUMAN_SUBMITTED}", "TitleState.KDP_DRAFT_READY: {TitleState.HUMAN_SUBMITTED, TitleState.LIVE}"),
        ("TitleState.RIGHTS_HOLD: {TitleState.VALIDATED}", "TitleState.RIGHTS_HOLD: {TitleState.VALIDATED, TitleState.DRAFTING}"),
        ("TitleState.POLICY_HOLD: {TitleState.HUMAN_RELEASE_REVIEW}", "TitleState.POLICY_HOLD: {TitleState.HUMAN_RELEASE_REVIEW, TitleState.KDP_DRAFT_READY}"),
        ("TitleState.HUMAN_RELEASE_REVIEW: {TitleState.KDP_DRAFT_READY, TitleState.POLICY_HOLD}", "TitleState.HUMAN_RELEASE_REVIEW: {TitleState.KDP_DRAFT_READY}"),
        ("TitleState.DRAFTING: {TitleState.EDITING, TitleState.POLICY_HOLD}", "TitleState.DRAFTING: {TitleState.EDITING}"),
        ("return target in _ALLOWED.get(current, set())", "return True"),
    ]),
    "src/kdp_pipeline/providers/costs.py": (["tests/integration/test_sprint6_provider_costs.py"], [
        ("if estimate > budget.max_run_estimated_cost_usd:", "if estimate >= budget.max_run_estimated_cost_usd * 2:"),
        ("if projected > budget.monthly_limit_usd and budget.hard_stop:", "if projected > budget.monthly_limit_usd * 1.5 and budget.hard_stop:"),
        ("projected = spent + reserved + (estimate or 0.0)", "projected = spent + (estimate or 0.0)"),
        ('BudgetReservationRow.status.in_(("reserved", "uncertain", "unpriced", "provider_outcome_unknown")),\n    )).all()\n    reserved', 'BudgetReservationRow.status.in_(("reserved",)),\n    )).all()\n    reserved'),
        ("if estimate is None and budget.hard_stop:", "if False:"),
        ("cached = min(cached_tokens or 0, input_tokens)", "cached = cached_tokens or 0"),
        ("if cost is not None and (not isfinite(float(cost)) or cost < 0):", "if cost is not None and not isfinite(float(cost)):"),
        ("if usage.reported_cost is not None:", "if False:"),
        ("input_token_bound = len((system_instructions + \"\\n\" + rendered_prompt).encode(\"utf-8\"))", "input_token_bound = len(rendered_prompt) // 4"),
        ("if row.created_at.strftime(\"%Y-%m\") == month and row.currency == \"USD\")", "if row.currency == \"USD\")"),
    ]),
}

def main() -> None:
    py = sys.executable
    total = killed = 0
    for rel, (tests, mutants) in TARGETS.items():
        for old, new in mutants:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "repo"
                shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", "audit", "__pycache__", ".pytest_cache"))
                target = work / rel
                src = target.read_text()
                if old not in src:
                    print(f"SKIP (pattern not found) {rel}: {old[:60]}"); continue
                target.write_text(src.replace(old, new, 1))
                r = subprocess.run([py, "-m", "pytest", "-q", "-x", "-p", "no:randomly", "-p", "no:cacheprovider", *tests],
                                   cwd=work, capture_output=True, text=True, env={"PYTHONPATH": str(work / "src"), "PATH": "/usr/bin:/bin"})
                total += 1
                status = "KILLED" if r.returncode != 0 else "SURVIVED"
                killed += status == "KILLED"
                print(f"{status:8} {rel}: {old[:70]!r} -> {new[:70]!r}", flush=True)
    print(f"\nmutation score: {killed}/{total} = {killed / max(total, 1):.0%}")

if __name__ == "__main__":
    main()
