"""Synthetic workload generator + timing for WS-N (no provider calls; FakeProvider-style capture).

python audit/lab/datagen.py --titles 1 5 20 --chapters 10 --words 3000
"""
from __future__ import annotations
import argparse, json, sys, tempfile, time, tracemalloc
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[1])]
from lab.kdplab import CaptureProvider, draft_and_accept, make_root, plan_title  # noqa: E402
from kdp_pipeline.build.service import build_manuscript  # noqa: E402
from kdp_pipeline.chapters.service import record_chapter_summary  # noqa: E402
from kdp_pipeline.inspection import doctor  # noqa: E402
from kdp_pipeline.workspace.inspection import inspect_workspace  # noqa: E402

def body(words: int, n: int) -> str:
    return f"# Chapter {n}\n\n" + " ".join(f"word{n}_{i}" for i in range(words)) + "\n"

def populate(root: Path, titles: int, chapters: int, words: int) -> list[str]:
    ids = []
    for t in range(titles):
        provider = CaptureProvider({f"chapter.draft.{n}": body(words, n) for n in range(1, chapters + 1)})
        book = plan_title(root, provider, chapters=chapters, name=f"Book {t}")
        for n in range(1, chapters + 1):
            _, accepted = draft_and_accept(book, provider, chapter=n)
            record_chapter_summary(root, book.title_id, n, accepted.accepted_asset.asset_id, f"summary {n}", "ed")
        ids.append(book.title_id)
    return ids

def timed(fn, *a, repeat=3, **kw):
    best = None
    for _ in range(repeat):
        t0 = time.perf_counter(); fn(*a, **kw); dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return round(best, 3)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--titles", type=int, nargs="+", default=[1, 5, 20])
    ap.add_argument("--chapters", type=int, default=10); ap.add_argument("--words", type=int, default=3000)
    ap.add_argument("--out", type=Path, default=Path("audit/evidence/perf/perf.json")); a = ap.parse_args()
    results = []
    for n in a.titles:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp)); t0 = time.perf_counter()
            ids = populate(root, n, a.chapters, a.words); setup = time.perf_counter() - t0
            tracemalloc.start()
            home = timed(inspect_workspace, root)
            peak = tracemalloc.get_traced_memory()[1] / 1e6; tracemalloc.stop()
            results.append({"titles": n, "chapters_per_title": a.chapters, "words_per_chapter": a.words,
                            "setup_s": round(setup, 1), "home_page_snapshot_s": home, "snapshot_peak_mb": round(peak, 1),
                            "doctor_s": timed(doctor, root, repeat=1),
                            "build_one_title_s": timed(build_manuscript, root, title_id=ids[0], builder="b", repeat=1)})
            print(json.dumps(results[-1]), flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_text(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
