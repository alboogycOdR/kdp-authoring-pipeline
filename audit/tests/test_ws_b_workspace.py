"""WS-B — Workspace web application security, exercised over HTTP against the real server."""

from __future__ import annotations

import asyncio
import html
import json
import re
import socket
import time
from pathlib import Path

import pytest

from lab.kdplab import (CaptureProvider, Workspace, add_fake_priced_profile, draft_and_accept,
                        make_root, plan_title, rows)
from lab.c1_chain import run_c1
from kdp_pipeline.storage.service import create_project, create_title
from kdp_pipeline.verification.service import add_verification_flag

HOSTILE = ('<script>window.__pwned=1</script><img src=x onerror="window.__pwned=2">'
           '"\'><svg onload=alert(1)></textarea>')


# ------------------------------------------------------------------ C1 chain / auth model

def test_KDP_AUD_001_unauthenticated_peer_forges_full_release_approval(root, evidence, monkeypatch):
    """A client with only HTTP reach drives a book from nothing to an approved, frozen release
    packet, authorising paid generation and every 'human' decision under invented names.
    With an operator-identity header required (set by an authenticating proxy), a peer that
    cannot present one must be unable to approve a release. The peer never sends the header."""
    monkeypatch.setenv("KDP_WORKSPACE_OPERATOR_HEADER", "X-KDP-Operator")
    result = run_c1(root)
    (evidence / "c1_transcript.json").write_text(json.dumps(result, indent=2))
    assert result["candidate_status"] != "approved_for_manual_kdp_action", (
        "Unauthenticated peer produced an approved-for-manual-KDP release packet "
        f"({result['packet_id']}) under self-declared names {result['distinct_actor_names']}")


def test_KDP_AUD_050_post_with_absent_origin_is_accepted(root, evidence):
    """`if origin and origin != ...` accepts a POST that sends no Origin header at all.
    A hardened server should require a same-origin signal (Origin or Sec-Fetch-Site) for state change."""
    book = plan_title(root)
    with Workspace(root) as ws:
        token = ws.csrf(f"/titles/{book.title_id}")
        # No Origin header and no Sec-Fetch-Site; a valid CSRF token (which any page reader has).
        status, _, _ = ws.post(f"/titles/{book.title_id}/actions/scan-scripture",
                               {"csrf_token": token, "operator": "peer"}, headers={"Origin": None})
        (evidence / "absent_origin.json").write_text(json.dumps({"status_without_origin": status}))
    assert status == 403, f"POST without an Origin header was accepted (status {status}), not rejected"


def test_POS_cross_origin_and_missing_token_are_rejected(root):
    book = plan_title(root)
    with Workspace(root) as ws:
        token = ws.csrf(f"/titles/{book.title_id}")
        bad_origin, _, _ = ws.post(f"/titles/{book.title_id}/actions/scan-scripture",
                                   {"csrf_token": token, "operator": "peer"},
                                   headers={"Origin": "http://evil.example"})
        no_token, _, _ = ws.post(f"/titles/{book.title_id}/actions/scan-scripture", {"operator": "peer"})
        assert bad_origin == 403 and no_token == 403
        assert inspect_items(root) == 0


def inspect_items(root: Path) -> int:
    return rows(root, "select count(*) n from verification_items")[0]["n"]


# ------------------------------------------------------------------ output encoding / XSS

def test_POS_hostile_names_are_html_inert(root, evidence):
    """Hostile markup in operator-controlled fields (project name, title) must render escaped."""
    project = create_project(root, HOSTILE + " project")
    create_title(root, project.project_id, HOSTILE + " title")
    with Workspace(root) as ws:
        _, _, home = ws.get("/")
        _, _, proj = ws.get(f"/projects/{project.project_id}")
    (evidence / "home.html").write_text(home)
    for page in (home, proj):
        assert "<script>window.__pwned" not in page
        assert "onerror=\"window.__pwned" not in page
        assert "&lt;script&gt;" in page  # escaped form present


def test_POS_hostile_model_output_is_escaped_in_review(root, evidence):
    """Hostile text returned by the provider and shown on a review page must be inert;
    the CSP must forbid inline script."""
    provider = CaptureProvider({"chapter.draft.1": f"# Chapter One\n\n{HOSTILE}\n"})
    book = plan_title(root, provider)
    draft = asyncio.run(_draft(book, provider))
    with Workspace(root) as ws:
        status, headers, page = ws.get(f"/reviews/asset/{draft}")
    (evidence / "review.html").write_text(page)
    csp = headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp and "<script>window.__pwned" not in page
    assert "&lt;script&gt;" in page


async def _draft(book, provider):
    from kdp_pipeline.chapter import ChapterService
    result = await ChapterService.draft(book.root, title_id=book.title_id, chapter_number=1, provider=provider)
    return result.asset.asset_id


# ------------------------------------------------------------------ response headers

def test_KDP_AUD_017_security_headers_on_redirect_and_405(root, evidence):
    book = plan_title(root)
    add_fake_priced_profile(root, project_id=book.project_id, monthly=5, per_run=0.5)
    with Workspace(root) as ws:
        token = ws.csrf(f"/titles/{book.title_id}")
        red_status, red_headers, _ = ws.post(f"/titles/{book.title_id}/actions/scan-scripture",
                                             {"csrf_token": token, "operator": "op"},
                                             headers={"Origin": f"http://{ws.host}"})
        m_status, m_headers, _ = ws.request("PUT", "/")
    evidence.joinpath("headers.json").write_text(json.dumps({
        "redirect_status": red_status, "redirect_headers": red_headers,
        "method_not_allowed_status": m_status, "mna_headers": m_headers}, indent=2))
    for label, hdrs in (("303", red_headers), ("405", m_headers)):
        assert hdrs.get("Content-Security-Policy"), f"{label} response lacks Content-Security-Policy"
        assert hdrs.get("X-Content-Type-Options") == "nosniff", f"{label} response lacks nosniff"


# ------------------------------------------------------------------ robustness

def test_POS_route_id_rejects_traversal_and_bad_verbs(root):
    with Workspace(root) as ws:
        for path in ("/titles/..%2f..%2fetc", "/projects/%00", "/reviews/asset/..", "/titles/a/edit/..%2f.."):
            status, _, _ = ws.get(path)
            assert status in (400, 404), (path, status)
        for verb in ("PUT", "DELETE", "PATCH"):
            status, headers, _ = ws.request(verb, "/")
            assert status == 405 and "GET" in headers.get("Allow", "")


def test_KDP_AUD_053_head_and_get_diverge_for_review_pages(root, evidence):
    """do_HEAD renders workspace/help/healthz/404 only; for a real review URL it returns 404
    though GET returns 200. HEAD should mirror GET's status for the same resource."""
    book = plan_title(root)
    item = add_verification_flag(root, title_id=book.title_id, kind="source_claim",
                                 locator="ch1", exact_text="claim", reviewer="author")
    with Workspace(root) as ws:
        get_status, _, _ = ws.get(f"/reviews/verification/{item.verification_id}")
        head_status, _, _ = ws.request("HEAD", f"/reviews/verification/{item.verification_id}")
    (evidence / "head_get.json").write_text(json.dumps({"get": get_status, "head": head_status}))
    assert get_status == head_status, f"GET returns {get_status} but HEAD returns {head_status} for the same page"
