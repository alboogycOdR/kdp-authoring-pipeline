"""WS-K: read-only page rendering, screenshots at four viewports, and axe-core WCAG scan.

Only GET requests are issued. Seeds a sandbox title with the fake provider first.
python audit/lab/browser/ui_a11y_scan.py
"""
from __future__ import annotations
import asyncio, json, re, sys, tempfile
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[3] / "src"), str(HERE.parents[2])]
from lab.kdplab import CaptureProvider, Workspace, add_fake_priced_profile, draft_and_accept, make_root, plan_title  # noqa: E402
from kdp_pipeline.chapter import ChapterService  # noqa: E402
from kdp_pipeline.verification.service import add_verification_flag  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

AXE = Path("/tmp/claude-0/axe/node_modules/axe-core/axe.min.js").read_text()
OUT = HERE.parents[2] / "evidence" / "ui"
VIEWPORTS = {"1440x900": (1440, 900), "1024x768": (1024, 768), "768x1024": (768, 1024), "390x844": (390, 844)}

def seed(root: Path) -> dict:
    provider = CaptureProvider({"chapter.draft": "# Chapter One\n\nA short synthetic chapter. [SCRIPTURE NEEDED]\n"})
    book = plan_title(root, provider, chapters=2)
    _, acc = draft_and_accept(book, provider, chapter=1)
    from kdp_pipeline.chapters.service import record_chapter_summary
    record_chapter_summary(root, book.title_id, 1, acc.accepted_asset.asset_id, "Chapter one summary.", "editor")
    draft2 = asyncio.run(ChapterService.draft(root, title_id=book.title_id, chapter_number=2, provider=provider))
    add_fake_priced_profile(root, project_id=book.project_id, monthly=5, per_run=0.5)
    flag = add_verification_flag(root, title_id=book.title_id, kind="source_claim", locator="ch1", exact_text="claim", reviewer="author")
    return {"home": "/", "help": "/help", "project": f"/projects/{book.project_id}", "title": f"/titles/{book.title_id}",
            "review_asset": f"/reviews/asset/{draft2.asset.asset_id}", "review_verification": f"/reviews/verification/{flag.verification_id}",
            "editor": f"/titles/{book.title_id}/edit/{draft2.asset.asset_id}", "not_found": "/nope"}

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp)); pages = seed(root)
        report, by_rule = {}, Counter()
        with Workspace(root) as ws, sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            for vp, (w, h) in VIEWPORTS.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, bypass_csp=True)
                page = ctx.new_page()
                for name, path in pages.items():
                    page.goto(f"http://127.0.0.1:{ws.port}{path}")
                    page.screenshot(path=str(OUT / f"{name}-{vp}.png"), full_page=True)
                    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                    entry = report.setdefault(name, {"overflow_viewports": []})
                    if overflow: entry["overflow_viewports"].append(vp)
                    if vp == "1440x900":
                        page.add_script_tag(content=AXE)
                        res = page.evaluate("async () => (await axe.run(document, {runOnly: ['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']})).violations")
                        entry["violations"] = [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]),
                                                "help": v["help"], "sample": v["nodes"][0]["html"][:160]} for v in res]
                        for v in res: by_rule[(v["id"], v["impact"])] += len(v["nodes"])
                        entry["text_len"] = len(page.inner_text("body"))
                        entry["ids_shown"] = len(re.findall(r"(?:AST|APR|JOB|FND|CAN|VRF|RGT|REL|BLD|PRJ|BK)-\d{8}-[A-F0-9]{8}", page.inner_text("body")))
                        entry["headings"] = page.evaluate("[...document.querySelectorAll('h1,h2,h3')].map(h=>h.tagName+':'+h.textContent.trim().slice(0,40))")[:15]
                ctx.close()
            # dark theme sample
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", bypass_csp=True); page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{ws.port}{pages['title']}")
            page.select_option("#theme-choice", "dark"); page.screenshot(path=str(OUT / "title-dark-1440x900.png"), full_page=True)
            page.add_script_tag(content=AXE)
            dark = page.evaluate("async () => (await axe.run(document, {runOnly: ['color-contrast']})).violations")
            report["title_dark_contrast"] = [{"nodes": len(v["nodes"]), "sample": v["nodes"][0]["html"][:160]} for v in dark]
            browser.close()
        summary = [{"rule": r, "impact": i, "nodes": n} for (r, i), n in by_rule.most_common()]
        (OUT / "a11y_report.json").write_text(json.dumps({"pages": report, "summary_by_rule": summary}, indent=2))
        print(json.dumps(summary, indent=1)); print({k: (v.get("overflow_viewports"), v.get("ids_shown")) for k, v in report.items() if isinstance(v, dict)})

if __name__ == "__main__":
    main()
