from __future__ import annotations

import html
import json
from urllib.parse import quote


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _title_url(title_id: str, section: str | None = None) -> str:
    return f"/titles/{quote(title_id, safe='')}" + (f"#{quote(section, safe='')}" if section else "")


def _link(title_id: str, label: str, section: str | None = None) -> str:
    return f'<a href="{_e(_title_url(title_id, section))}">{_e(label)}</a>'


def _review_link(kind: str, identifier: str, label: str | None = None) -> str:
    return (f'<a href="/reviews/{_e(kind)}/{_e(quote(identifier, safe=""))}">'
            f'{_e(label or identifier)}</a>')


def _status(text: object, kind: str = "neutral") -> str:
    return f'<span class="status status-{_e(kind)}">{_e(text)}</span>'


def _item(title_id: str, title: str, detail: str, section: str, kind: str,
          review: tuple[str, str, str] | None = None) -> str:
    review_html = (f'<p class="queue-review-link">{_review_link(*review)}</p>' if review else '')
    return (
        f'<li class="attention-item">{_status(kind.replace("-", " "), kind)}'
        f'<div><strong>{_link(title_id, title, section)}</strong>'
        f'<p>{_e(detail)}</p>{review_html}</div></li>'
    )


def _assets_needing_approval(report: dict) -> list[dict]:
    expected = {"concept.brief", "planning.positioning", "planning.book-brief", "planning.outline",
                "planning.chapter-card", "chapter.draft", "chapter.revision"}
    assets = report.get("assets", [])
    by_id = {asset.get("asset_id"): asset for asset in assets}
    accepted_lineage: set[str] = set()
    for asset in assets:
        if asset.get("approval_status") != "accepted":
            continue
        source_ref = asset.get("source_ref")
        while source_ref and source_ref in by_id and source_ref not in accepted_lineage:
            accepted_lineage.add(source_ref)
            source_ref = by_id[source_ref].get("source_ref")
    return [asset for asset in report.get("assets", [])
            if asset.get("approval_status") == "experimental" and asset.get("asset_type") in expected
            and asset.get("asset_id") not in accepted_lineage]


def _attention(snapshot: dict, project_id: str | None = None, query: str = "") -> tuple[dict[str, list[str]], list[dict]]:
    project = next((item for item in snapshot["projects"] if item["project_id"] == project_id), None)
    allowed = set(project["title_ids"]) if project else set(snapshot["titles"])
    if query:
        q = query.casefold()
        matched_projects = {item["project_id"] for item in snapshot["projects"]
                            if q in item["project_id"].casefold() or q in item["name"].casefold()}
        project_titles = {tid for item in snapshot["projects"] if item["project_id"] in matched_projects
                          for tid in item["title_ids"]}
        allowed = {tid for tid in allowed if tid in project_titles or q in tid.casefold()
                   or q in snapshot["titles"][tid]["title"]["working_title"].casefold()}
    queues: dict[str, list[str]] = {
        "Needs Review": [], "Needs Approval": [], "Needs Verification": [],
        "Blocked": [], "Ready": [],
    }
    ready_titles = []
    for title_id in sorted(allowed):
        report = snapshot["titles"].get(title_id)
        if not report:
            continue
        title = report["title"]["working_title"]
        has_attention = False
        invalid_findings = set(report.get("continuity", {}).get("findings_from_invalid_analysis", []))
        for finding in report.get("findings", []):
            if finding.get("status") == "open":
                suspect = (" From an invalid or unverified continuity attempt; do not use as guidance."
                           if finding.get("finding_id") in invalid_findings else "")
                queues["Needs Review"].append(_item(
                    title_id, title, f"{finding.get('pass_type', 'Editorial')} finding {finding.get('finding_id')} is open.{suspect}",
                    "editorial", "review"))
                has_attention = True
        for recommendation in report.get("editorial", {}).get("revision_recommendations", []):
            if recommendation.get("status") == "open":
                queues["Needs Review"].append(_item(
                    title_id, title, f"Revision recommendation {recommendation.get('recommendation_id')} for chapter {recommendation.get('chapter_number')} awaits review.",
                    "editorial", "review"))
                has_attention = True
        for asset in _assets_needing_approval(report):
            queues["Needs Approval"].append(_item(
                title_id, title, f"{asset.get('asset_type')} asset {asset.get('asset_id')} is experimental and awaits human acceptance.",
                "planning" if asset.get("asset_type", "").startswith(("concept.", "planning.")) else "chapters",
                "approval", ("asset", asset["asset_id"], "Review artefact")))
            has_attention = True
        for proposal in report.get("proposals", []):
            if proposal.get("status") == "proposed":
                queues["Needs Approval"].append(_item(
                    title_id, title, f"Canon proposal {proposal.get('proposal_id')} awaits human review.",
                    "editorial", "approval", ("canon", proposal["proposal_id"], "Review proposal")))
                has_attention = True
        verification = report.get("verification", {})
        for item in verification.get("items", []):
            if item.get("status") == "pending":
                queues["Needs Verification"].append(_item(
                    title_id, title, f"{item.get('kind')} item {item.get('verification_id')} · {item.get('locator')}",
                    "verification", "verification", ("verification", item["verification_id"], "Review verification")))
                has_attention = True
        for record in verification.get("rights_records", []):
            if record.get("status") == "pending":
                queues["Needs Verification"].append(_item(
                    title_id, title, f"Rights record {record.get('rights_record_id')} · {record.get('material_type')}",
                    "verification", "verification", ("rights", record["rights_record_id"], "Review rights")))
                has_attention = True
        for approval in report.get("chapter_workflow", {}).get("verification_conditions", []):
            for condition in approval.get("conditions", []):
                queues["Needs Verification"].append(_item(
                    title_id, title, f"Approval condition {approval.get('approval_id')}: {condition}",
                    "conditions", "verification"))
                has_attention = True
        for build in report.get("builds", {}).get("records", []):
            if build.get("status") == "blocked":
                queues["Blocked"].append(_item(
                    title_id, title, f"Build {build.get('build_id')} is blocked.", "builds", "blocked"))
                has_attention = True
        for candidate in report.get("release", {}).get("candidates", []):
            if candidate.get("status") in {"blocked", "held", "stale"}:
                queues["Blocked"].append(_item(
                    title_id, title, f"Release candidate {candidate.get('candidate_id')} is {candidate.get('status')}.",
                    "release", "blocked", ("release", candidate["candidate_id"], "Review candidate")))
                has_attention = True
            elif candidate.get("status") == "pending_human_review":
                queues["Needs Approval"].append(_item(
                    title_id, title, f"Release candidate {candidate.get('candidate_id')} awaits human review.",
                    "release", "approval", ("release", candidate["candidate_id"], "Review candidate")))
                has_attention = True
        if str(report.get("title", {}).get("status", "")).endswith("_HOLD"):
            queues["Blocked"].append(_item(
                title_id, title, f"Title status is {report['title']['status']}.", "overview", "blocked"))
            has_attention = True
        planning = report.get("planning", {})
        planning_complete = bool(planning) and all(item.get("complete") for item in planning.values())
        if not has_attention and planning_complete and report["title"].get("status") in {"PLANNED", "DRAFTING"}:
            ready_titles.append({"title_id": title_id, "title": title,
                                 "status": report["title"].get("status", "—")})
    queues["Ready"] = [
        f'<li class="attention-item">{_status(item["status"], "ready")}<div>'
        f'<strong>{_link(item["title_id"], item["title"])}</strong>'
        '<p>No surfaced review or release blocker. This is not release approval.</p></div></li>'
        for item in ready_titles
    ]
    visible_ids = allowed | {item["project_id"] for item in snapshot["projects"]
                             if not project or item["project_id"] == project_id}
    events = [event for event in snapshot.get("recent_activity", [])
              if (event.get("correlation_id") in visible_ids or event.get("entity_id") in visible_ids)]
    return queues, events[:12]


def _queue_section(name: str, items: list[str], empty: str) -> str:
    return (f'<section class="queue-section"><header><h2>{_e(name)}</h2>'
            f'<span class="count">{len(items)}</span></header>'
            + (f'<ul class="attention-list">{"".join(items)}</ul>' if items
               else f'<p class="empty-note">{_e(empty)}</p>') + '</section>')


def _activity(events: list[dict]) -> str:
    if not events:
        return '<p class="empty-note">No recent activity.</p>'
    items = []
    for event in events:
        items.append(
            '<li><time>' + _e(event.get("timestamp")) + '</time><strong>'
            + _e(event.get("action", "Activity")) + '</strong><span>'
            + _e(event.get("entity_type")) + ' ' + _e(event.get("entity_id"))
            + ' · ' + _e(event.get("result")) + '</span></li>'
        )
    return '<ul class="activity-list">' + ''.join(items) + '</ul>'


def _project_link(project: dict) -> str:
    project_url = f"/projects/{quote(project['project_id'], safe='')}"
    provider = project.get("provider")
    provider_text = (f"{provider['display_name']} · {provider['model']} · "
                     f"{'configuration ready · not connected' if provider['ready'] else 'check settings'}"
                     if provider else "No provider selected")
    return (
        f'<li class="project-row"><a href="{_e(project_url)}"><strong>{_e(project["name"])}</strong>'
        f'<span>{_e(project["project_id"])} · {_e(project["status"])}</span></a>'
        f'<span class="project-provider">{_e(provider_text)}</span></li>'
    )


def _title_link(title_id: str, report: dict) -> str:
    title = report["title"]
    plans = report.get("planning", {})
    plans_complete = sum(bool(value.get("complete")) for value in plans.values())
    verification_count = len(report.get("verification", {}).get("release_blockers", []))
    release_candidates = report.get("release", {}).get("candidates", [])
    blocked = sum(candidate.get("status") in {"blocked", "held", "stale"} for candidate in release_candidates)
    return (
        f'<li class="title-row"><a href="{_e(_title_url(title_id))}"><strong>{_e(title["working_title"])}</strong>'
        f'<span>{_e(title_id)} · {_e(title.get("status"))}</span></a>'
        f'<span>{plans_complete}/{len(plans)} planning · {report.get("chapter_lifecycle", {}).get("accepted_chapter_count", 0)} accepted chapters · '
        f'{verification_count} verification blockers · {blocked} blocked candidates</span></li>'
    )


def _workspace_content(snapshot: dict, project_id: str | None = None, query: str = "") -> str:
    selected_project = next((p for p in snapshot["projects"] if p["project_id"] == project_id), None)
    if project_id and selected_project is None:
        return _empty_workspace(f"Project {project_id} was not found.")
    queues, events = _attention(snapshot, project_id, query)
    attention = ''.join(_queue_section(name, queues[name], empty) for name, empty in (
        ("Needs Review", "No open editorial findings."),
        ("Needs Approval", "No assets or proposals are waiting for acceptance."),
        ("Needs Verification", "No pending verification or rights items."),
        ("Blocked", "No builds or release candidates are blocked."),
        ("Ready", "No titles currently meet the ready-for-next-step conditions."),
    ))
    if selected_project:
        budget = snapshot["budgets"].get(project_id, {})
        provider = selected_project.get("provider")
        provider_summary = (f"{provider['display_name']} · {provider['model']} · "
                            f"{'configuration ready · not connected' if provider['ready'] else 'check settings'}"
                            if provider else "No provider selected")
        usage_summary = (f"Known USD cost ${budget.get('spent_usd', 0):.4f} · "
                         f"{budget.get('unknown_cost_events', 0)} unknown-cost events")
        project_header = (
            '<section class="project-focus"><p class="breadcrumb"><a href="/">Workspace</a> / Project</p>'
            f'<h1>{_e(selected_project["name"])}</h1><p>{_e(project_id)} · {_e(selected_project["status"])}</p>'
            f'<p>Provider: {_e(provider_summary)}</p><p>Budget: {_e(usage_summary)}</p>'
            f'<p class="muted">{_e(budget.get("warning") or "No budget warning reported.")}</p></section>'
        )
        projects_html = ''
        title_ids = selected_project["title_ids"]
        titles = ''.join(_title_link(tid, snapshot["titles"][tid]) for tid in title_ids if tid in snapshot["titles"])
        titles_html = '<section class="directory"><h2>Titles</h2>' + (
            f'<ul class="title-list">{titles}</ul>' if titles else '<p class="empty-note">No titles in this project.</p>') + '</section>'
    else:
        project_header = '<section class="welcome"><h1>Workspace</h1><p>Work that needs attention is listed first. Status summaries never approve or publish.</p></section>'
        matching_projects = snapshot["projects"]
        matching_titles = snapshot["titles"].items()
        if query:
            q = query.casefold()
            matching_projects = [p for p in matching_projects if q in p["name"].casefold() or q in p["project_id"].casefold()]
            matched_project_titles = {tid for p in matching_projects for tid in p["title_ids"]}
            matching_titles = [(tid, r) for tid, r in matching_titles
                               if tid in matched_project_titles or q in r["title"]["working_title"].casefold() or q in tid.casefold()]
        projects_html = '<section class="directory"><h2>Projects</h2>' + (
            '<ul class="project-list">' + ''.join(_project_link(p) for p in matching_projects)
            + '</ul>' if matching_projects else '<p class="empty-note">No matching projects.</p>') + '</section>'
        title_rows = ''.join(_title_link(tid, report) for tid, report in matching_titles)
        titles_html = '<section class="directory"><h2>Titles</h2>' + (
            f'<ul class="title-list">{title_rows}</ul>' if title_rows else '<p class="empty-note">No matching titles.</p>') + '</section>'
    activity_html = '<section class="recent-activity"><h2>Recent Activity</h2>' + _activity(events) + '</section>'
    return project_header + '<section class="attention"><h2 class="section-title">Attention</h2>' + attention + '</section>' + activity_html + projects_html + titles_html


def _empty_workspace(message: str) -> str:
    return ('<section class="welcome"><h1>Workspace</h1><p>' + _e(message) + '</p>'
            '<p>Initialize the local workspace from the CLI with <code>kdp init-db</code>, then reload this page.</p></section>')


def render_workspace(snapshot: dict | None, *, project_id: str | None = None, query: str = "") -> str:
    if snapshot is None:
        body = _empty_workspace("The local workspace database is not available yet.")
    else:
        body = _workspace_content(snapshot, project_id, query[:100])
    return _page("Workspace", body, query=query)


def _section_cards(report: dict, title_id: str) -> dict[str, str]:
    planning = report.get("planning", {})
    plan_items = []
    for kind, value in planning.items():
        accepted = value.get("accepted", [])
        ids = ', '.join(item.get("asset_id", "") for item in accepted) or "No accepted asset"
        plan_items.append(f'<li><strong>{_e(kind.replace("_", " ").title())}</strong><span>{_e(ids)}</span>{_status("complete" if value.get("complete") else "missing", "ready" if value.get("complete") else "blocked")}</li>')
    chapters = report.get("chapter_workflow", {}).get("chapters", [])
    chapter_items = [f'<li><strong>Chapter { _e(item.get("chapter_number")) }</strong><span>{_e(item.get("status"))}</span>{_status("accepted" if item.get("accepted") else "in progress", "ready" if item.get("accepted") else "review")}</li>' for item in chapters]
    findings = report.get("findings", [])
    finding_items = [f'<li><strong>{_e(item.get("finding_id"))}</strong><span>{_e(item.get("pass_type"))} · {_e(item.get("severity"))} · {_e(item.get("location"))}</span>{_status(item.get("status"), "review" if item.get("status") == "open" else "ready")}</li>' for item in findings]
    proposals = report.get("proposals", [])
    proposal_items = [f'<li><strong>{_review_link("canon", item["proposal_id"])}</strong><span>Finding {_e(item.get("finding_id"))}</span>{_status(item.get("status"), "approval" if item.get("status") == "proposed" else "neutral")}</li>' for item in proposals]
    verify = report.get("verification", {})
    verification_items = [f'<li><strong>{_review_link("verification", item["verification_id"])}</strong><span>{_e(item.get("kind"))} · {_e(item.get("locator"))} · {_e(item.get("exact_text"))}</span>{_status(item.get("status"), "verification" if item.get("status") == "pending" else "ready")}</li>' for item in verify.get("items", [])]
    rights_items = [f'<li><strong>{_review_link("rights", item["rights_record_id"])}</strong><span>{_e(item.get("material_type"))} · {_e(item.get("description"))}</span>{_status(item.get("status"), "verification" if item.get("status") == "pending" else "ready")}</li>' for item in verify.get("rights_records", [])]
    builds = report.get("builds", {}).get("records", [])
    build_items = [f'<li><strong>{_e(item.get("build_id"))}</strong><span>{_e(item.get("output_format"))} · {_e(item.get("output_sha256"))}</span>{_status(item.get("status"), "blocked" if item.get("status") == "blocked" else "ready")}</li>' for item in builds]
    candidates = report.get("release", {}).get("candidates", [])
    candidate_items = [f'<li><strong>{_review_link("release", item["candidate_id"])}</strong><span>{len(item.get("current_blockers", []))} blockers · review record { _e(item.get("approval_id")) }</span>{_status(item.get("status"), "blocked" if item.get("status") in {"blocked", "stale", "held"} else "approval")}</li>' for item in candidates]
    provider = report.get("provider")
    provider_selected = bool(provider and provider.get("provider_id"))
    if provider_selected:
        provider_ready = bool(provider.get("enabled") and
                              (provider.get("provider_type") != "openai-compatible" or provider.get("api_key_configured")))
        provider_state = "Configured · not connected" if provider_ready else "Check provider settings"
        provider_summary = (f'<li><strong>{_e(provider.get("display_name"))}</strong>'
                            f'<span>{_e(provider.get("provider_id"))} · {_e(provider.get("model"))}</span>'
                            f'{_status(provider_state, "ready" if provider_ready else "blocked")}</li>')
    else:
        provider_summary = '<li class="empty-note">No provider selected.</li>'
    budget = report.get("budget", {})
    usage = report.get("usage", {})
    budget_summary = (f'<p>Known USD cost: ${_e(budget.get("spent_usd", 0))} · unknown-cost events: {_e(budget.get("unknown_cost_events", 0))}</p>'
                      f'<p>Monthly limit: ${_e(budget.get("monthly_limit_usd"))} · hard stop: {_e(budget.get("hard_stop"))}</p>'
                      f'<p>{_e(budget.get("warning") or "No budget warning reported.")}</p>'
                      f'<p>Monthly tokens in/out: {_e(usage.get("monthly_input_tokens", 0))}/{_e(usage.get("monthly_output_tokens", 0))}</p>')
    conditions = report.get("chapter_workflow", {}).get("verification_conditions", [])
    condition_items = [f'<li><strong>{_e(item.get("approval_id"))}</strong><span>{_e(" ".join(item.get("conditions", [])))}</span></li>' for item in conditions]
    pending_assets = _assets_needing_approval(report)
    pending_items = [f'<li><strong>{_review_link("asset", item["asset_id"])}</strong>'
                     f'<span>{_e(item["asset_type"])} · experimental</span>{_status("Needs human review", "approval")}</li>'
                     for item in pending_assets]
    return {
        "pending": _records(pending_items, "No experimental content artefacts await acceptance."),
        "planning": _records(plan_items, "No planning artefacts recorded."),
        "chapters": _records(chapter_items, "No chapters tracked."),
        "editorial": _records(finding_items + proposal_items, "No findings or canon proposals."),
        "verification": _records(verification_items + rights_items, "No verification or rights records."),
        "builds": _records(build_items, "No manuscript builds."),
        "release": _records(candidate_items, "No release candidates."),
        "provider": '<ul class="record-list">' + provider_summary + '</ul>' + budget_summary,
        "conditions": _records(condition_items, "No recorded chapter conditions."),
    }


def _records(items: list[str], empty: str) -> str:
    return '<ul class="record-list">' + ''.join(items) + '</ul>' if items else f'<p class="empty-note">{_e(empty)}</p>'


def _action_form(title_id: str, action: str, token: str, label: str, fields: str = "") -> str:
    return (f'<form method="post" action="/titles/{_e(quote(title_id, safe=""))}/actions/{_e(action)}">'
            f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
            f'{fields}<button type="submit">{_e(label)}</button></form>')


def _operator() -> str:
    return '<label>Operator name<input name="operator" required maxlength="100" autocomplete="name"></label>'


def _workflow_actions(report: dict, title_id: str, token: str) -> str:
    if not token:
        return ""
    flag_fields = (_operator() + '<label>Kind<select name="kind">'
                   '<option value="source_claim">Source claim</option><option value="research">Research</option>'
                   '<option value="expert_review">Expert review</option><option value="sensitivity">Sensitivity</option>'
                   '</select></label><label>Locator<input name="locator" required maxlength="200"></label>'
                   '<label>Exact text or claim<textarea name="exact_text" required maxlength="2000" rows="3"></textarea></label>'
                   '<label>Asset ID, if applicable<input name="asset_id" maxlength="80"></label>')
    rights_fields = (_operator() + '<label>Material type<input name="material_type" required maxlength="100"></label>'
                     '<label>Description<textarea name="description" required maxlength="2000" rows="3"></textarea></label>'
                     '<label>Asset ID, if applicable<input name="asset_id" maxlength="80"></label>'
                     '<label>Source<input name="source" maxlength="500"></label>'
                     '<label>Provenance reference<input name="provenance_reference" maxlength="500"></label>'
                     '<label>Legal basis<input name="legal_basis" maxlength="500"></label>'
                     '<label>Evidence reference<input name="evidence_reference" maxlength="500"></label>')
    queue_fields = (_operator() + '<label>From chapter<input name="start" type="number" min="1" max="999" value="1" required></label>'
                    '<label>Through chapter<input name="through" type="number" min="1" max="999" value="1" required></label>')
    builds = report.get("builds", {}).get("records", [])
    candidates = report.get("release", {}).get("candidates", [])
    build_options = ''.join(f'<option value="{_e(row["build_id"])}">{_e(row["build_id"])} · {_e(row["status"])}</option>' for row in builds)
    candidate_options = ''.join(f'<option value="{_e(row["candidate_id"])}">{_e(row["candidate_id"])} · {_e(row["status"])}</option>' for row in candidates)
    candidate_form = (_action_form(title_id, "create-candidate", token, "Create release candidate",
        _operator() + f'<label>Manuscript build<select name="build_id" required>{build_options}</select></label>')
        if builds else '<p class="empty-note">Create a manuscript build first.</p>')
    packet_form = (_action_form(title_id, "export-packet", token, "Export review packet",
        _operator() + f'<label>Release candidate<select name="candidate_id" required>{candidate_options}</select></label>')
        if candidates else '<p class="empty-note">Create a release candidate first.</p>')
    return (
        '<section class="title-section workflow-actions" id="actions"><h2>Workflow actions</h2>'
        '<p>Each action updates the local record through an audited service. Enter your name for actions that require an operator.</p>'
        '<div class="action-grid">'
        '<div class="action-group"><h3>Verification</h3><p>Queue placeholders from accepted chapters; this does not verify references or change manuscript text.</p>'
        + _action_form(title_id, "scan-scripture", token, "Scan Scripture placeholders")
        + '<details><summary>Add a verification flag</summary>'
        + _action_form(title_id, "add-flag", token, "Add flag", flag_fields) + '</details>'
        + '<details><summary>Record rights material</summary>'
        + _action_form(title_id, "add-rights", token, "Add rights record", rights_fields) + '</details></div>'
        '<div class="action-group"><h3>Chapter queue</h3><p>Queue at most ten chapters. Queueing and resuming do not generate content.</p>'
        + _action_form(title_id, "queue-chapters", token, "Queue chapters", queue_fields)
        + _action_form(title_id, "pause-queue", token, "Pause queued chapters", _operator())
        + _action_form(title_id, "resume-queue", token, "Resume paused chapters", _operator()) + '</div>'
        '<div class="action-group"><h3>Manuscript build</h3><p>Assemble accepted chapters in Markdown. Unresolved conditions keep the build blocked.</p>'
        + _action_form(title_id, "build-manuscript", token, "Create Markdown build", _operator()) + '</div>'
        '<div class="action-group"><h3>Release preparation</h3><p>Freeze a build into a candidate and export a review packet. These actions never approve or publish.</p>'
        + candidate_form + packet_form + '</div></div></section>'
    )


def render_title(snapshot: dict, title_id: str, *, csrf_token: str = "", notice: str = "", error: bool = False) -> str:
    report = snapshot.get("titles", {}).get(title_id)
    if not report:
        return _page("Title not found", _empty_workspace(f"Title {title_id} was not found."))
    title = report["title"]
    project_id = report.get("project", {}).get("project_id")
    sections = _section_cards(report, title_id)
    blockers = report.get("verification", {}).get("release_blockers", [])
    blocked_builds = [row for row in report.get("builds", {}).get("records", []) if row.get("status") == "blocked"]
    blocked_release = [row for row in report.get("release", {}).get("candidates", []) if row.get("status") in {"blocked", "stale", "held"}]
    attention_label = "No active blockers surfaced" if not blockers and not blocked_builds and not blocked_release else f"{len(blockers) + len(blocked_builds) + len(blocked_release)} items need attention"
    body = (
        f'<p class="breadcrumb"><a href="/">Workspace</a> / '
        f'<a href="/projects/{_e(quote(project_id or "", safe=""))}">Project</a> / Title</p>'
        f'<header class="title-heading"><div><h1>{_e(title.get("working_title"))}</h1>'
        f'<p>{_e(title_id)} · {_e(title.get("status"))}</p></div>{_status(attention_label, "blocked" if "items need" in attention_label else "ready")}</header>'
        '<nav class="section-nav" aria-label="Title sections">'
        + ''.join(f'<a href="#{name}">{label}</a>' for name, label in (
            ("overview", "Overview"), ("pending", "Awaiting acceptance"), ("actions", "Actions"),
            ("planning", "Planning"), ("chapters", "Chapters"),
            ("editorial", "Editorial and canon"), ("verification", "Verification and rights"),
            ("builds", "Builds"), ("release", "Release"), ("provider", "Provider and budget"),
            ("conditions", "Approval conditions"))) + '</nav>'
        + f'<section class="title-section" id="overview"><h2>Overview</h2><p>Project <a href="/projects/{_e(quote(project_id or "", safe=""))}">{_e(project_id or "—")}</a></p>'
        f'<p>{_e(report.get("chapter_lifecycle", {}).get("accepted_chapter_count", 0))} accepted chapters · '
        f'{len(blockers)} verification blockers</p></section>'
        + (f'<div class="action-notice {"action-error" if error else "action-success"}" role="status">{_e(notice)}</div>' if notice else '')
        + f'<section class="title-section" id="pending"><h2>Awaiting acceptance</h2>{sections["pending"]}</section>'
        + _workflow_actions(report, title_id, csrf_token)
        + ''.join(f'<section class="title-section" id="{name}"><h2>{label}</h2>{sections[key]}</section>' for name, label, key in (
            ("planning", "Planning", "planning"), ("chapters", "Chapters", "chapters"),
            ("editorial", "Editorial and canon", "editorial"), ("verification", "Verification and rights", "verification"),
            ("builds", "Builds", "builds"), ("release", "Release", "release"),
            ("provider", "Provider and budget", "provider"), ("conditions", "Approval conditions", "conditions")))
        + f'<section class="title-section"><h2>Inspection</h2><p>{_e(len(report.get("inconsistencies", [])))} inconsistencies</p>'
        + ("<ul>" + ''.join(f'<li>{_e(item)}</li>' for item in report.get("continuity", {}).get("warnings", [])) + "</ul>"
           if report.get("continuity", {}).get("warnings") else '<p class="empty-note">No continuity inspection warnings.</p>')
        + '</section>'
    )
    return _page(title.get("working_title", "Title"), body)


def render_not_found(message: str = "Page not found") -> str:
    return _page("Not found", _empty_workspace(message))


def _review_list(items: list[str], empty: str) -> str:
    return '<ul class="review-list">' + ''.join(f'<li>{_e(item)}</li>' for item in items) + '</ul>' if items else f'<p class="empty-note">{_e(empty)}</p>'


def _review_json(value: object) -> str:
    return '<pre class="review-data">' + _e(json.dumps(value, indent=2, ensure_ascii=False, default=str)) + '</pre>'


def _release_checklist(dossier: dict, csrf_token: str) -> str:
    if dossier["kind"] != "release" or not dossier["can_decide"]:
        return ""
    artefact = dossier["artefact"]
    groups = (("Metadata", "metadata", artefact["metadata_checks"]),
              ("AI disclosure", "ai_disclosure", {"ai_use_disclosure": artefact["ai_disclosure"]}),
              ("Current KDP checks", "kdp", artefact["kdp_checks"]))
    forms = []
    for heading, domain, checks in groups:
        pending = [(key, value) for key, value in checks.items()
                   if value.get("status") not in {"complete", "not_applicable"}]
        if not pending:
            continue
        forms.append(f'<h3>{_e(heading)}</h3>')
        for key, value in pending:
            fields = ('<label>Reviewer name<input name="reviewer" required maxlength="100"></label>'
                      '<label>Decision<select name="decision"><option value="complete">Complete</option>'
                      '<option value="not_applicable">Not applicable</option></select></label>'
                      '<label>Rationale<textarea name="rationale" required maxlength="2000" rows="2"></textarea></label>'
                      '<label>Evidence reference<input name="evidence_reference" required maxlength="500"></label>')
            if domain == "metadata":
                fields += '<label>Reviewed value, if relevant<input name="value" maxlength="500"></label>'
            if domain == "ai_disclosure":
                fields += '<label>Human-reviewed disclosure statement<textarea name="statement" maxlength="2000" rows="2"></textarea></label>'
            fields += ('<label class="review-confirm"><input type="checkbox" name="confirm_consequences" value="yes" required>'
                       ' I reviewed the candidate context above and this check.</label>')
            forms.append(
                f'<details><summary>{_e(key.replace("_", " ").title())} · {_e(value.get("status", "pending"))}</summary>'
                f'<form class="review-form" method="post" action="/reviews/release/{_e(quote(dossier["id"], safe=""))}/check">'
                f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
                f'<input type="hidden" name="review_hash" value="{_e(dossier["review_hash"])}">'
                f'<input type="hidden" name="domain" value="{_e(domain)}">'
                f'<input type="hidden" name="key" value="{_e(key)}">'
                + fields + '<div class="review-buttons"><button type="submit">Record this check</button></div></form></details>'
            )
    if not forms:
        return '<section class="title-section review-section"><h2>Release checklist</h2><p>All checklist entries have human decisions recorded.</p></section>'
    return ('<section class="title-section review-section release-checklist"><h2>Release checklist</h2>'
            '<p>Complete each check against current evidence. Recording a check does not approve the candidate.</p>'
            + ''.join(forms) + '</section>')


def render_review(dossier: dict, csrf_token: str, *, notice: str = "", error: bool = False) -> str:
    kind = dossier["kind"]
    title_id = dossier["title_id"]
    artefact = dossier["artefact"]
    if kind == "asset":
        asset_content = artefact.get("content")
        artefact_html = ('<dl class="review-facts">' + ''.join(
            f'<div><dt>{_e(label)}</dt><dd>{_e(artefact.get(key))}</dd></div>'
            for key, label in (("asset_id", "Asset ID"), ("type", "Type"), ("path", "Workspace path"),
                               ("sha256", "Registered SHA-256"), ("hash_matches", "Hash matches"),
                               ("source_ref", "Source asset"), ("creator_type", "Creator type"),
                               ("creator", "Creator"), ("version", "Version"),
                               ("accepted_asset_id", "Accepted asset"), ("approval_id", "Approval ID"))) + '</dl>'
            + ('<h3>Complete artefact text</h3><pre class="review-data">' + _e(asset_content) + '</pre>'
               if asset_content is not None else '<p class="review-warning">The complete artefact cannot be displayed. Acceptance is disabled.</p>')
            + ('<h3>Concept scorecards</h3>' + _review_json(artefact["scorecards"])
               if artefact.get("scorecards") else ''))
    else:
        if kind == "canon":
            artefact_html = ('<dl class="review-facts">' + ''.join(
                f'<div><dt>{_e(label)}</dt><dd>{_e(artefact.get(key))}</dd></div>'
                for key, label in (("proposal_id", "Proposal ID"), ("entity_id", "Canon entity"),
                                   ("field", "Field"), ("reviewer", "Decision reviewer"),
                                   ("reviewed_at", "Decision date"))) + '</dl>'
                + '<h3>Current value</h3>' + _review_json(artefact.get("current_value"))
                + '<h3>Proposed value</h3>' + _review_json(artefact.get("proposed_value"))
                + '<h3>Reason</h3><p>' + _e(artefact.get("reason")) + '</p>'
                + '<h3>Evidence assets</h3>' + _review_list(artefact.get("evidence_asset_ids", []), "No evidence assets linked.")
                + '<h3>Affected assets</h3>' + _review_list(artefact.get("affected_assets", []), "No affected assets listed."))
        elif kind == "release":
            manuscript = artefact.get("manuscript")
            candidate_details = {key: value for key, value in artefact.items() if key != "manuscript"}
            artefact_html = _review_json(candidate_details)
            artefact_html += ('<h3>Complete manuscript build</h3><p>Hash: ' + _e(manuscript.get("sha256"))
                              + ' · matches: ' + _e(manuscript.get("hash_matches")) + '</p>'
                              + '<pre class="review-data">' + _e(manuscript["content"]) + '</pre>'
                              if manuscript and manuscript.get("content") is not None
                              else '<p class="review-warning">The complete build manuscript cannot be displayed. Approval is disabled.</p>')
        else:
            artefact_html = _review_json(artefact)
    provenance = dossier["provenance"]
    provenance_html = ''.join(_review_json(item) for item in provenance) if provenance else '<p class="empty-note">No linked provenance record was found.</p>'
    findings_html = ''.join(_review_json(item) for item in dossier["findings"]) if dossier["findings"] else '<p class="empty-note">No linked findings recorded.</p>'
    if dossier.get("related_proposals"):
        findings_html += '<h3>Related canon proposals</h3>' + _review_list(dossier["related_proposals"], "")
    decisions = {
        "asset": [("accept", "Accept this artefact")],
        "canon": [("accepted", "Accept proposal"), ("rejected", "Reject proposal")],
        "release": [("approve", "Approve for manual KDP action"), ("hold", "Hold candidate"), ("reject", "Reject candidate")],
        "verification": [("verified", "Mark verified"), ("not_verified", "Mark not verified"), ("not_applicable", "Mark not applicable")],
        "rights": [("cleared", "Clear rights"), ("restricted", "Mark restricted"), ("not_applicable", "Mark not applicable")],
    }[kind]
    fields = '<label>Reviewer name<input name="reviewer" required maxlength="100" autocomplete="name"></label>'
    if kind == "asset":
        mandatory = next((c for c in dossier["conditions"] if "[SCRIPTURE NEEDED]" in c), "")
        fields += ('<label>Approval conditions (one per line, maximum five)'
                   f'<textarea name="conditions" rows="4" maxlength="2600">{_e(mandatory)}</textarea></label>'
                   '<p class="muted">Conditions are recorded with the approval and remain release blockers until resolved through the verification workflow.</p>')
    else:
        fields += '<label>Rationale<textarea name="rationale" required maxlength="2000" rows="3"></textarea></label>' if kind in {"release", "verification", "rights"} else ''
    if kind == "verification":
        fields += ('<label>Evidence reference<input name="evidence_reference" maxlength="500"></label>'
                   '<label>Exact Scripture or source reference, if applicable<input name="proposed_reference" maxlength="200"></label>'
                   '<label>Translation or source policy, if applicable<input name="source_policy" maxlength="500"></label>'
                   '<p class="muted">Verified decisions require evidence. Scripture verification also requires an exact reference and source policy.</p>')
    fields += ('<label class="review-confirm"><input type="checkbox" name="confirm_consequences" value="yes" required>'
               ' I reviewed the artefact, provenance, findings, blockers, conditions, and consequences shown above.</label>')
    buttons = ''.join(
        f'<button type="submit" name="decision" value="{_e(value)}"'
        + (' disabled title="Resolve blockers before approval"' if value in {"approve", "accepted", "cleared"} and dossier["blockers"] else '')
        + f'>{_e(label)}</button>' for value, label in decisions)
    if dossier["can_decide"]:
        decision_html = (f'<form class="review-form" method="post" action="/reviews/{_e(kind)}/{_e(quote(dossier["id"], safe=""))}/decide">'
                         f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
                         f'<input type="hidden" name="review_hash" value="{_e(dossier["review_hash"])}">'
                         + fields + '<div class="review-buttons">' + buttons + '</div></form>')
    else:
        decision_html = '<p class="review-warning">This record is no longer available for a decision from this page.</p>'
    body = (
        f'<p class="breadcrumb"><a href="/">Workspace</a> / <a href="{_e(_title_url(title_id))}">{_e(dossier["title"])}</a> / Review</p>'
        f'<header class="title-heading"><div><h1>Review {_e(kind)}</h1><p>{_e(dossier["id"])} · {_e(dossier["status"])}</p></div>'
        f'{_status(dossier["status"], "approval")}</header>'
        + (f'<div class="action-notice {"action-error" if error else "action-success"}" role="status">{_e(notice)}</div>' if notice else '')
        + '<section class="title-section review-section"><h2>1. Artefact</h2>' + artefact_html + '</section>'
        + '<section class="title-section review-section"><h2>2. Provenance</h2>' + provenance_html + '</section>'
        + '<section class="title-section review-section"><h2>3. Findings</h2>' + findings_html + '</section>'
        + '<section class="title-section review-section"><h2>4. Blockers</h2>'
        + _review_list(dossier["blockers"], "No blockers identified for this decision.") + '</section>'
        + '<section class="title-section review-section"><h2>5. Conditions</h2>'
        + _review_list(dossier["conditions"], "No existing conditions recorded.") + '</section>'
        + '<section class="title-section review-section"><h2>6. Consequences</h2><p>'
        + _e(dossier["consequence"]) + '</p></section>'
        + _release_checklist(dossier, csrf_token)
        + '<section class="title-section review-section" id="decision"><h2>7. Human decision</h2>'
        + decision_html + '</section>'
    )
    return _page(f'Review {kind}', body)


def _page(title: str, body: str, query: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f'<title>{_e(title)} · KDP Pipeline Workspace</title>'
        '<link rel="stylesheet" href="/static/workspace.css">'
        '<script src="/static/workspace.js" defer></script></head><body data-theme="brand">'
        '<a class="skip-link" href="#main">Skip to content</a>'
        '<header class="app-header"><a class="wordmark" href="/" aria-label="KDP Pipeline Workspace home">'
        '<span class="mark" aria-hidden="true"><i></i><i></i><i></i></span><span>KDP Pipeline</span></a>'
        '<div class="header-tools"><form action="/" method="get" role="search">'
        f'<label class="visually-hidden" for="workspace-search">Search projects and titles</label><input id="workspace-search" name="q" type="search" value="{_e(query)}" placeholder="Search projects and titles">'
        '<button type="submit">Search</button></form>'
        '<label class="theme-label" for="theme-choice">Theme</label><select id="theme-choice" name="theme" aria-label="Choose workspace theme">'
        '<option value="brand">Brand</option><option value="light">Light</option><option value="dark">Dark</option></select></div></header>'
        f'<main id="main">{body}</main>'
        '<footer class="app-footer"><span>Local operator workspace</span>'
        '<span>SQLite remains the system of record. Actions require an explicit operator; this workspace cannot approve or publish.</span></footer>'
        '</body></html>'
    )
