"""Chain C1 — an unauthenticated peer drives a whole book to an approved, frozen
release packet over HTTP only, using self-declared operator/reviewer names.

Precondition (the one legitimate setup step, as a system operator would do): one
enabled, priced provider profile exists. Here it is a FakeProvider so no network
or key is involved. Everything after that is plain HTTP against the real
Workspace server: scrape the process-global CSRF token from a GET page, then POST
every "human" decision. No legitimate human is ever involved and every name is
invented.

`run_c1(root)` returns a transcript dict. The test in test_ws_b_workspace.py
asserts the peer reached `approved_for_manual_kdp_action` with a frozen packet.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lab.kdplab import Workspace, add_fake_priced_profile, rows

_AST = re.compile(r"AST-\d{8}-[A-F0-9]{8}")
_TITLE = re.compile(r"BK-\d{8}-[A-F0-9]{8}")
_BUILD = re.compile(r"BLD-\d{8}-[A-F0-9]{8}")
_CANDIDATE = re.compile(r"REL-\d{8}-[A-F0-9]{8}")
_PACKET = re.compile(r"PKT-\d{8}-[A-F0-9]{8}")


class ForgedPeer:
    """Only ever performs GET and POST over HTTP; never touches services or the DB."""

    def __init__(self, ws: Workspace, name: str = "Mallory (forged)"):
        self.ws = ws
        self.name = name
        self.steps: list[dict[str, Any]] = []

    def _log(self, label: str, status: int, note: str = "") -> None:
        self.steps.append({"n": len(self.steps) + 1, "label": label, "status": status, "note": note})

    def token(self, path: str = "/") -> str:
        return self.ws.csrf(path)

    def _flash_page(self, location: str) -> str:
        # Follow a 303 to read the flash notice (where new asset IDs are shown to any client).
        status, _, page = self.ws.get(location)
        return page

    def create_book(self, provider_id: str) -> str | None:
        token = self.token("/")
        status, headers, _ = self.ws.post("/books", {
            "csrf_token": token, "operator": self.name, "project_name": "Forged project",
            "title_name": "A Book Nobody Approved", "audience": "Teen founders, ages 13-16",
            "idea": "Synthetic idea used only to exercise the approval path.",
            "provider_id": provider_id, "monthly_usd": "9999", "max_run_usd": "9999"})
        if status != 303:
            self._log(f"POST /books BLOCKED (status {status}) — no authenticated operator", status)
            return None
        title_id = _TITLE.search(headers["Location"]).group(0)
        self._log("POST /books (create project+title+budget, name self-declared)", status,
                  f"budget set to $9999/mo by the peer; title {title_id}")
        return title_id

    def generate(self, title_id: str, action: str, fields: dict[str, str]) -> str:
        token = self.token(f"/titles/{title_id}")
        body = {"csrf_token": token, "operator": self.name, "confirm_cost": "yes", **fields}
        status, headers, _ = self.ws.post(f"/titles/{title_id}/actions/{action}", body)
        assert status == 303, (action, status, headers)
        page = self._flash_page(headers["Location"])
        asset_id = _AST.search(page).group(0)
        self._log(f"POST generate:{action} (paid call authorised by the peer)", status, f"asset {asset_id}")
        return asset_id

    def accept_asset(self, title_id: str, asset_id: str, decision: str = "accept") -> None:
        review_hash = self.ws.review_hash("asset", asset_id)
        token = self.token(f"/reviews/asset/{asset_id}")
        status, headers, body = self.ws.post(f"/reviews/asset/{asset_id}/decide", {
            "csrf_token": token, "review_hash": review_hash, "confirm_consequences": "yes",
            "reviewer": self.name, "decision": decision})
        assert status == 303, (asset_id, status, body[:200])
        self._log(f"POST accept asset {asset_id} (forged human acceptance)", status)

    def act(self, title_id: str, action: str, fields: dict[str, str]) -> str:
        token = self.token(f"/titles/{title_id}")
        status, headers, body = self.ws.post(f"/titles/{title_id}/actions/{action}",
                                             {"csrf_token": token, "operator": self.name, **fields})
        assert status == 303, (action, status, body[:200])
        return headers["Location"]

    def release_check(self, candidate_id: str, domain: str, key: str, statement: str = "") -> None:
        review_hash = self.ws.review_hash("release", candidate_id)
        token = self.token(f"/reviews/release/{candidate_id}")
        fields = {"csrf_token": token, "review_hash": review_hash, "confirm_consequences": "yes",
                  "domain": domain, "key": key, "decision": "complete", "reviewer": self.name,
                  "rationale": "Reviewed by the forged operator.", "evidence_reference": "none"}
        if statement:
            fields["statement"] = statement
        status, _, body = self.ws.post(f"/reviews/release/{candidate_id}/check", fields)
        assert status == 303, (domain, key, status, body[:200])

    def approve_release(self, candidate_id: str) -> None:
        review_hash = self.ws.review_hash("release", candidate_id)
        token = self.token(f"/reviews/release/{candidate_id}")
        status, _, body = self.ws.post(f"/reviews/release/{candidate_id}/decide", {
            "csrf_token": token, "review_hash": review_hash, "confirm_consequences": "yes",
            "reviewer": self.name, "decision": "approve", "rationale": "Forged approval."})
        assert status == 303, (status, body[:300])
        self._log("POST approve release (forged human release decision)", status)


def run_c1(root: Path) -> dict:
    """Drive the full chain and return a transcript + the resulting DB state."""
    provider_id = add_fake_priced_profile(root, "fake-ready")  # legitimate operator setup
    with Workspace(root) as ws:
        peer = ForgedPeer(ws)
        title_id = peer.create_book(provider_id)
        if title_id is None:
            return {"title_id": None, "candidate_id": None, "packet_id": None,
                    "candidate_status": "blocked", "candidate_created_by": None,
                    "release_approvals": [], "distinct_actor_names": [], "steps": peer.steps}

        # Concept path (the create-book flow enables the concept gate, so positioning
        # acceptance needs an accepted concept brief first).
        audience = peer.generate(title_id, "audience-brief", {"audience": "Teen founders"})
        seeds = peer.generate(title_id, "concept-seeds", {"asset_id": audience})
        brief = peer.generate(title_id, "concept-enrich", {"asset_id": seeds, "selection": "seed A"})
        peer.accept_asset(title_id, brief)

        # Planning: generate, then accept each artefact.
        positioning = peer.generate(title_id, "positioning", {})
        peer.accept_asset(title_id, positioning)
        peer.act(title_id, "advance-validated", {})
        book_brief = peer.generate(title_id, "book-brief", {})
        peer.accept_asset(title_id, book_brief)
        outline = peer.generate(title_id, "outline", {})
        peer.accept_asset(title_id, outline)
        card = peer.generate(title_id, "chapter-card", {"chapter_number": "1"})
        peer.accept_asset(title_id, card)
        peer.act(title_id, "advance-planned", {})
        peer.act(title_id, "advance-drafting", {})

        # Draft and accept a chapter.
        draft = peer.generate(title_id, "draft-chapter", {"chapter_number": "1"})
        peer.accept_asset(title_id, draft)

        # Build -> candidate -> pass every checklist item -> approve.
        loc = peer.act(title_id, "build-manuscript", {})
        build_id = _BUILD.search(peer._flash_page(loc)).group(0)
        peer._log(f"POST build-manuscript ({build_id})", 303)
        loc = peer.act(title_id, "create-candidate", {"build_id": build_id})
        candidate_id = _CANDIDATE.search(peer._flash_page(loc)).group(0)
        peer._log(f"POST create-candidate ({candidate_id})", 303)

        from kdp_pipeline.release.service import KDP_CHECKS, METADATA_CHECKS
        for key in METADATA_CHECKS:
            peer.release_check(candidate_id, "metadata", key)
        for key in KDP_CHECKS:
            peer.release_check(candidate_id, "kdp", key)
        peer.release_check(candidate_id, "ai_disclosure", "ai_use_disclosure",
                           statement="No AI disclosure actually reviewed.")
        peer.approve_release(candidate_id)
        loc = peer.act(title_id, "export-packet", {"candidate_id": candidate_id})
        peer._flash_page(loc)
        packet_id = rows(root, "select packet_id from release_packets order by created_at desc")[0]["packet_id"]
        peer._log(f"POST export-packet ({packet_id}) — frozen release packet exported", 303)

    candidate = rows(root, "select status, created_by from release_candidate_records where candidate_id=?",
                     candidate_id)[0]
    approval = rows(root, "select approver, decision from approvals where scope='release_candidate'")
    distinct_names = sorted({r["approver"] for r in approval} |
                            {r["actor_id"] for r in rows(root, "select distinct actor_id from audit_events")})
    return {"title_id": title_id, "candidate_id": candidate_id, "packet_id": packet_id,
            "candidate_status": candidate["status"], "candidate_created_by": candidate["created_by"],
            "release_approvals": approval, "distinct_actor_names": distinct_names,
            "steps": peer.steps}
