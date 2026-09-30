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


def _actor_field(name: str = "operator") -> str:
    return (f'<p class="muted actor-note">This action will be recorded under your signed-in account.</p>'
            f'<input type="hidden" name="{_e(name)}" value="authenticated operator">')


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


def _provider_options(snapshot: dict) -> str:
    return ''.join(
        f'<option value="{_e(p["provider_id"])}">{_e(p["display_name"])} · {_e(p["model"])}</option>'
        for p in snapshot.get("available_providers", []) if p["ready"] and p["priced"]
    )


def _start_form(snapshot: dict, token: str) -> str:
    if not token:
        return ""
    options = _provider_options(snapshot)
    if not options:
        return ('<section class="start-book" id="start"><h2>Start a new book</h2>'
                '<p>No enabled provider has both a configured credential and model pricing. '
                'Ask the system operator to configure one before creating a book.</p></section>')
    return (
        '<section class="start-book" id="start"><h2>Start a new book</h2>'
        '<p>Save your idea, create a project and title, and set a hard spending limit. '
        'Creating the book makes no AI request; generation is a separate, confirmed step.</p>'
        '<form method="post" action="/books">'
        f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
        + _actor_field() +
        '<label>Project name<input name="project_name" required maxlength="200" placeholder="A book or series workspace"></label>'
        '<label>Working book title<input name="title_name" required maxlength="200"></label>'
        '<label>Who is the book for?<textarea name="audience" required maxlength="1000" rows="2" placeholder="Reader age or stage, interests, and need"></textarea></label>'
        '<label>Your book idea<textarea name="idea" required maxlength="4000" rows="4" placeholder="What is the book about? What will the reader experience or gain?"></textarea></label>'
        f'<label>AI provider<select name="provider_id" required>{options}</select></label>'
        '<label>Monthly AI spending limit (USD)<input name="monthly_usd" type="number" min="0.01" max="10000" step="0.01" required></label>'
        '<label>Maximum estimated cost per AI request (USD)<input name="max_run_usd" type="number" min="0.01" max="10000" step="0.01" required></label>'
        '<p class="muted">The limits are hard stops for future requests. Provider billing may differ from local estimates.</p>'
        '<button type="submit">Create book and save idea</button></form></section>'
    )


def _project_forms(snapshot: dict, project_id: str, token: str) -> str:
    if not token:
        return ""
    options = _provider_options(snapshot)
    add_title = (
        f'<form method="post" action="/projects/{_e(quote(project_id, safe=""))}/actions/new-title">'
        f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
        + _actor_field() +
        '<label>Working title<input name="title_name" required maxlength="200"></label>'
        '<button type="submit">Add title to this project</button></form>'
    )
    controls = (
        f'<form method="post" action="/projects/{_e(quote(project_id, safe=""))}/actions/controls">'
        f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
        + _actor_field() +
        f'<label>Priced provider<select name="provider_id" required>{options}</select></label>'
        '<label>Monthly limit (USD)<input name="monthly_usd" type="number" min="0.01" step="0.01" required></label>'
        '<label>Per-request limit (USD)<input name="max_run_usd" type="number" min="0.01" step="0.01" required></label>'
        '<button type="submit">Save provider and hard budget</button></form>' if options else
        '<p class="empty-note">No ready, priced provider is available for browser generation.</p>'
    )
    return ('<section class="start-book"><h2>Manage this project</h2><details><summary>Add a book title</summary>'
            + add_title + '</details><details><summary>Provider and spending limits</summary>'
            + controls + '</details></section>')


def _workspace_content(snapshot: dict, project_id: str | None = None, query: str = "",
                       token: str = "") -> str:
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
    entry = _project_forms(snapshot, project_id, token) if project_id else _start_form(snapshot, token)
    return project_header + entry + '<section class="attention"><h2 class="section-title">Attention</h2>' + attention + '</section>' + activity_html + projects_html + titles_html


def _empty_workspace(message: str) -> str:
    return ('<section class="welcome"><h1>Workspace</h1><p>' + _e(message) + '</p>'
            '<p>Initialize the local workspace from the CLI with <code>kdp init-db</code>, then reload this page.</p></section>')


def render_workspace(snapshot: dict | None, *, project_id: str | None = None, query: str = "",
                     csrf_token: str = "", notice: str = "", error: bool = False) -> str:
    if snapshot is None:
        body = _empty_workspace("The local workspace database is not available yet.")
    else:
        body = _workspace_content(snapshot, project_id, query[:100], csrf_token)
    if notice:
        body = f'<div class="action-notice {"action-error" if error else "action-success"}" role="status">{_e(notice)}</div>' + body
    return _page("Workspace", body, query=query, csrf_token=csrf_token)


def render_login(csrf_token: str, *, notice: str = "", error: bool = False,
                 configured: bool = True, next_path: str = "/") -> str:
    if not configured:
        body = ('<section class="login-panel"><div class="login-mark" aria-hidden="true">K</div>'
                '<h1>Workspace access is not configured</h1>'
                '<p>Ask the system administrator to configure the operator account before opening the Workspace.</p>'
                '</section>')
        return _page("Access setup", body)
    notice_html = (f'<p class="action-notice action-error" role="alert">{_e(notice)}</p>' if notice else '')
    body = (
        '<section class="login-panel"><div class="login-mark" aria-hidden="true">K</div>'
        '<p class="login-kicker">KDP Pipeline</p><h1>Welcome back</h1>'
        '<p class="login-intro">Sign in to continue to your book workspace.</p>' + notice_html +
        '<form method="post" action="/login" class="login-form">'
        f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
        f'<input type="hidden" name="next" value="{_e(next_path)}">'
        '<label for="login-username">Username</label>'
        '<input id="login-username" name="username" type="text" autocomplete="username" '
        'autocapitalize="none" spellcheck="false" required maxlength="80">'
        '<label for="login-password">Password</label>'
        '<input id="login-password" name="password" type="password" autocomplete="current-password" required>'
        '<label class="remember-choice"><input name="remember_me" type="checkbox" value="yes">'
        '<span>Remember me on this device for 30 days</span></label>'
        '<button class="primary-action" type="submit">Sign in</button></form>'
        '<p class="login-footnote">Use “Remember me” only on a device you trust.</p></section>'
    )
    return _page("Sign in", body)


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
                     f'<span>{_e(item["asset_type"])} · experimental'
                     + (f' · <a href="/titles/{_e(quote(title_id, safe=""))}/edit/{_e(quote(item["asset_id"], safe=""))}">Edit in browser</a>'
                        if item["asset_type"] in {"concept.brief", "planning.positioning", "planning.book-brief",
                                                    "planning.outline", "planning.chapter-card", "chapter.draft", "chapter.revision"} else '')
                     + f'</span>{_status("Needs human review", "approval")}</li>'
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
    is_generation = action in {"audience-brief", "concept-seeds", "concept-enrich", "concept-score",
                  "concept-drafting-brief", "positioning", "book-brief", "outline",
                  "chapter-card", "draft-chapter", "continuity", "developmental",
                  "editorial-pass", "revise-chapter"}
    if is_generation:
        fields = _operator() + fields
    return (f'<form method="post" action="/titles/{_e(quote(title_id, safe=""))}/actions/{_e(action)}"'
            + (' data-provider-call="true"' if is_generation else '') + '>'
            f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
            f'{fields}<button type="submit">{_e(label)}</button></form>')


def _authoring_stage_open(report: dict, stage: str) -> str:
    """Keep the title page focused on the stage the operator is in."""
    status = (report.get("title") or {}).get("status", "IDEA")
    active = {"IDEA": "concept", "VALIDATED": "planning", "PLANNED": "drafting",
              "DRAFTING": "drafting"}.get(status, "concept")
    return " open" if active == stage else ""


def _stage_banner(report: dict) -> str:
    title = report.get("title") or {}
    status = title.get("status", "IDEA")
    stages = (("IDEA", "Idea"), ("VALIDATED", "Planning"), ("PLANNED", "Drafting"),
              ("DRAFTING", "Review"), ("EDITING", "Verify"), ("PREFLIGHT_PASSED", "Release"))
    current_index = next((i for i, (key, _) in enumerate(stages) if key == status), 0)
    if status == "IDEA":
        next_title, next_copy, next_href = "Shape your concept", "Start by enabling concept review, then develop the idea you want to write.", "#authoring"
    elif status == "VALIDATED":
        next_title, next_copy, next_href = "Plan the book", "Create and accept the positioning, brief, outline, and chapter cards.", "#authoring"
    elif status == "PLANNED":
        next_title, next_copy, next_href = "Start drafting", "Move into drafting, then work through one chapter at a time.", "#authoring"
    elif status == "DRAFTING":
        next_title, next_copy, next_href = "Draft and review the next chapter", "Read each experimental result before accepting it into the manuscript.", "#authoring"
    else:
        next_title, next_copy, next_href = "Review what needs attention", "Use the sections below to resolve findings, verification items, or release conditions.", "#pending"
    items = []
    for index, (key, label) in enumerate(stages):
        state = "current" if index == current_index else ("complete" if index < current_index else "upcoming")
        items.append(f'<li class="stage-{state}"><span>{index + 1}</span>{_e(label)}</li>')
    return ('<section class="next-step" aria-labelledby="next-step-title">'
            f'<div class="next-step-copy"><p class="eyebrow">Current stage · {_e(dict(stages).get(status, status.replace("_", " ").title()))}</p>'
            f'<h2 id="next-step-title">{_e(next_title)}</h2><p>{_e(next_copy)}</p>'
            f'<a class="next-step-link" href="{_e(next_href)}">Go to the next step</a></div>'
            f'<ol class="stage-tracker" aria-label="Book journey">{"".join(items)}</ol></section>')


def _operator() -> str:
    return _actor_field()


def _authoring_actions(report: dict, title_id: str, token: str) -> str:
    if not token:
        return ""
    assets = report.get("assets", [])
    def options(*types: str, accepted: bool | None = None) -> str:
        return ''.join(
            f'<option value="{_e(item["asset_id"])}">{_e(item["asset_type"])} · {_e(item["asset_id"])} · {_e(item.get("approval_status"))}</option>'
            for item in assets if item.get("asset_type") in types
            and (accepted is None or (item.get("approval_status") == "accepted") == accepted)
        )
    def select(*types: str, accepted: bool | None = None) -> str:
        choices = options(*types, accepted=accepted)
        return f'<label>Source artefact<select name="asset_id" required>{choices}</select></label>' if choices else '<p class="empty-note">Required source artefact is not available yet.</p>'
    cost = ('<label class="review-confirm"><input type="checkbox" name="confirm_cost" value="yes" required>'
            ' I understand this sends context to the selected AI provider and incurs usage cost.</label>')
    chapter = '<label>Chapter number<input name="chapter_number" type="number" min="1" max="999" value="1" required></label>'
    budget = report.get("budget", {})
    provider = report.get("provider") or {}
    cost_note = (f'<p class="muted">Provider: {_e(provider.get("display_name", "none selected"))} · '
                 f'hard budget: {_e(budget.get("hard_stop", False))} · '
                 f'monthly ${_e(budget.get("monthly_limit_usd"))} · '
                 f'per request ${_e(budget.get("max_run_estimated_cost_usd"))}. '
                 'Each generation action is one request; review its result before another.</p>')
    concept = (
        f'<details class="action-group workflow-stage"{_authoring_stage_open(report, "concept")}><summary><h3>1. Develop your idea</h3></summary><p>Your saved idea informs the audience brief. Review each experimental result before continuing.</p>'
        + (_action_form(title_id, "save-idea", token, "Save starting idea",
            _operator() + '<label>Intended reader<textarea name="audience" required maxlength="1000" rows="2"></textarea></label>'
            + '<label>Book idea<textarea name="idea" required maxlength="4000" rows="4"></textarea></label>')
           if not options("concept.idea-note") else '<p>Your starting idea is saved.</p>')
        + _action_form(title_id, "concept-enable", token, "Enable concept review", _operator())
        + '<details><summary>Generate audience brief</summary>'
        + _action_form(title_id, "audience-brief", token, "Generate audience brief",
            '<label>Reader definition<textarea name="audience" required maxlength="1000" rows="2"></textarea></label>' + cost) + '</details>'
        + '<details><summary>Generate concept options</summary>'
        + _action_form(title_id, "concept-seeds", token, "Generate concept options",
            select("concept.audience-brief") + cost) + '</details>'
        + '<details><summary>Develop your chosen idea</summary>'
        + _action_form(title_id, "concept-enrich", token, "Develop concept brief",
            select("concept.seed-set") + '<label>Chosen idea or option<textarea name="selection" required maxlength="2000" rows="3"></textarea></label>' + cost) + '</details>'
        + '<details><summary>Validate and assess concept</summary>'
        + _action_form(title_id, "concept-validate", token, "Check concept completeness", select("concept.brief", accepted=False))
        + _action_form(title_id, "concept-score", token, "Generate advisory scorecard", select("concept.brief", accepted=False) + cost)
        + '<p>Open the concept brief under Awaiting acceptance to review and approve it yourself.</p></details>'
        + '<details><summary>Create drafting brief after concept approval</summary>'
        + _action_form(title_id, "concept-drafting-brief", token, "Generate drafting brief", select("concept.brief", accepted=True) + cost)
        + '</details></details>'
    )
    planning = (
        f'<details class="action-group workflow-stage"{_authoring_stage_open(report, "planning")}><summary><h3>2. Plan the book</h3></summary><p>Accept each planning artefact from its review page before advancing.</p>'
        + _action_form(title_id, "positioning", token, "Generate positioning", cost)
        + _action_form(title_id, "advance-validated", token, "Advance to validated", _operator())
        + _action_form(title_id, "book-brief", token, "Generate book brief", cost)
        + _action_form(title_id, "outline", token, "Generate outline", cost)
        + _action_form(title_id, "chapter-card", token, "Generate chapter card", chapter + cost)
        + _action_form(title_id, "advance-planned", token, "Advance to planned", _operator())
        + '</details>'
    )
    chapter_source = select("chapter.draft", "chapter.revision", accepted=False)
    editorial_passes = ''.join(f'<option value="{_e(p)}">{_e(p.replace("-", " ").title())}</option>'
                               for p in ("voice", "line", "copy", "reader-experience", "consistency"))
    drafting = (
        f'<details class="action-group workflow-stage"{_authoring_stage_open(report, "drafting")}><summary><h3>3. Draft and review chapters</h3></summary><p>Work on one chapter at a time. Generated chapters remain experimental until you accept them.</p>'
        + _action_form(title_id, "advance-drafting", token, "Start drafting stage", _operator())
        + _action_form(title_id, "draft-chapter", token, "Draft one chapter", chapter + cost)
        + '<details><summary>Analyze a draft</summary>'
        + _action_form(title_id, "continuity", token, "Run continuity analysis", chapter + chapter_source + cost)
        + _action_form(title_id, "developmental", token, "Run developmental analysis", chapter + chapter_source + cost)
        + _action_form(title_id, "editorial-pass", token, "Run selected editorial pass",
            chapter + chapter_source + f'<label>Pass<select name="pass_type">{editorial_passes}</select></label>' + cost)
        + '</details><details><summary>Revise and carry context forward</summary>'
        + _action_form(title_id, "revise-chapter", token, "Generate a revision", chapter + chapter_source + cost)
        + _action_form(title_id, "chapter-summary", token, "Save accepted chapter summary", chapter +
            select("chapter.accepted", accepted=True) + '<label>Continuity summary<textarea name="summary" required maxlength="3000" rows="3"></textarea></label>' + _operator())
        + '</details><p>Accept the chosen chapter draft or revision from Awaiting acceptance.</p></details>'
    )
    return ('<section class="title-section workflow-actions" id="authoring"><h2>Book authoring</h2>'
            + cost_note + '<div class="action-grid">' + concept + planning + drafting + '</div></section>')


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
        '<p>Each action updates the local record through an audited service. Actions are recorded under the signed-in account.</p>'
        '<div class="action-grid">'
        '<div class="action-group"><h3>Verification checks</h3><p>Run checks on accepted chapters and record human decisions. Checks never change manuscript text or verify a source automatically.</p>'
        + _action_form(title_id, "scan-scripture", token, "Scan manuscript placeholders")
        + '<p class="muted verification-note">This scan currently queues Scripture placeholders when they are present. Use verification flags for sources, claims, research, and other checks.</p>'
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
        + _stage_banner(report)
        + '<nav class="section-nav" aria-label="Title sections">'
        + ''.join(f'<a href="#{name}">{label}</a>' for name, label in (
            ("overview", "Overview"), ("authoring", "Book authoring"), ("jobs", "Recent jobs"),
            ("pending", "Awaiting acceptance"), ("actions", "Actions"),
            ("planning", "Planning"), ("chapters", "Chapters"),
            ("editorial", "Editorial and canon"), ("verification", "Verification and rights"),
            ("builds", "Builds"), ("release", "Release"), ("provider", "Provider and budget"),
            ("conditions", "Approval conditions"))) + '</nav>'
        + f'<section class="title-section" id="overview"><h2>Overview</h2><p>Project <a href="/projects/{_e(quote(project_id or "", safe=""))}">{_e(project_id or "—")}</a></p>'
        f'<p>{_e(report.get("chapter_lifecycle", {}).get("accepted_chapter_count", 0))} accepted chapters · '
        f'{len(blockers)} verification blockers</p></section>'
        + (f'<div class="action-notice {"action-error" if error else "action-success"}" role="status">{_e(notice)}</div>' if notice else '')
        + _authoring_actions(report, title_id, csrf_token)
        + '<section class="title-section" id="jobs"><h2>Recent jobs</h2><p>Check the result and usage before starting another paid request. If a connection fails, inspect the job before retrying.</p>'
        + _records([
            f'<li><strong>{_e(job.get("job_id"))}</strong><span>{_e(job.get("job_type"))} · '
            f'{_e(job.get("error") or job.get("provider_billing_warning") or job.get("usage_event_id") or "No usage event")}</span>'
            f'{_status(job.get("status"), "ready" if job.get("status") == "success" else "blocked")}</li>'
            for job in reversed(report.get("jobs", [])[-8:])], "No jobs recorded yet.")
        + '</section>'
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
    return _page(title.get("working_title", "Title"), body, csrf_token=csrf_token)


def render_help(csrf_token: str = "") -> str:
    """Explain the browser authoring journey without exposing operator CLI steps."""
    body = (
        '<div class="help-page">'
        '<section class="help-hero" aria-labelledby="help-title">'
        '<div class="help-hero-copy"><p class="help-kicker">Your guide to the Workspace</p>'
        '<h1 id="help-title">From your first idea to a book ready for review</h1>'
        '<p>You can create and manage your book here in the browser. Work through the stages below, '
        'review what the system creates, and make each important decision yourself.</p>'
        '<a class="help-primary" href="/#start">Start a new book</a>'
        '<a class="help-secondary" href="#journey">See the steps</a></div>'
        '<div class="help-book-art" aria-hidden="true"><div class="help-book-cover">'
        '<span class="help-book-line"></span><span class="help-book-line"></span>'
        '<span class="help-book-title">Your next<br>book starts<br>here.</span>'
        '<span class="help-book-rule"></span><span class="help-book-footer">IDEA → MANUSCRIPT</span>'
        '</div><span class="help-book-shadow"></span></div></section>'
        '<nav class="help-contents" aria-label="Help page sections">'
        '<a href="#journey">The journey</a><a href="#costs">AI and costs</a>'
        '<a href="#review">Review and approval</a><a href="#questions">Common questions</a></nav>'
        '<section class="help-intro" id="journey"><div><h2>Six stages, one book</h2>'
        '<p>Each stage leaves you with something you can inspect. You choose what to keep. '
        'If a step is blocked, open your title page and look at <strong>Attention</strong>, '
        '<strong>Awaiting acceptance</strong>, or <strong>Verification</strong> for the next action.</p></div>'
        '<p class="help-intro-note">Your work is saved under a <strong>project</strong>. '
        'Each book in that project is a <strong>title</strong>.</p></section>'
        '<ol class="help-journey">'
        '<li id="step-start"><div class="help-step-head"><span class="help-step-number">1</span>'
        '<div><p class="help-step-phase">Begin</p><h3>Save your idea</h3></div></div>'
        '<p>On the Workspace home page, choose <strong>Start a new book</strong>. Add your name, '
        'project name, working title, intended reader, and a short description of the idea. '
        'Select the available AI provider and set monthly and per-request spending limits.</p>'
        '<p class="help-step-outcome">What happens: your project, title, idea, and spending controls are saved. '
        'No AI request is made yet.</p></li>'
        '<li id="step-concept"><div class="help-step-head"><span class="help-step-number">2</span>'
        '<div><p class="help-step-phase">Explore</p><h3>Shape and approve the concept</h3></div></div>'
        '<p>Open your title and find <strong>Book authoring → Develop your idea</strong>. '
        'Create a reader brief, explore concept options, then develop the option you prefer. '
        'Check the concept brief for completeness and read it carefully. You can edit it in the browser.</p>'
        '<p class="help-step-outcome">Before continuing: open the concept under '
        '<strong>Awaiting acceptance</strong> and accept it only when it reflects the book you want.</p></li>'
        '<li id="step-plan"><div class="help-step-head"><span class="help-step-number">3</span>'
        '<div><p class="help-step-phase">Plan</p><h3>Set the book’s direction</h3></div></div>'
        '<p>Use <strong>Book authoring → Plan the book</strong> to create positioning, a book brief, '
        'an outline, and a card for each chapter. Review and accept each item from its review page. '
        'Use the stage buttons when the required work is accepted.</p>'
        '<p class="help-step-outcome">What you get: a clear promise to the reader and a chapter-by-chapter plan '
        'for drafting.</p></li>'
        '<li id="step-draft"><div class="help-step-head"><span class="help-step-number">4</span>'
        '<div><p class="help-step-phase">Write</p><h3>Draft and review one chapter at a time</h3></div></div>'
        '<p>Start the drafting stage, then choose <strong>Draft one chapter</strong>. Read the experimental '
        'draft. Run continuity or editorial analysis if useful, make a browser revision, and decide which '
        'version to accept. Repeat for later chapters, using a chapter summary to carry context forward.</p>'
        '<p class="help-step-outcome">Remember: generated text is a draft. It becomes accepted manuscript '
        'content only after your explicit review and acceptance.</p></li>'
        '<li id="step-verify"><div class="help-step-head"><span class="help-step-number">5</span>'
        '<div><p class="help-step-phase">Check</p><h3>Resolve sources, claims, and rights</h3></div></div>'
        '<p>Under <strong>Workflow actions → Verification checks</strong>, run the checks that fit your book. '
        'Scripture and quotation placeholders, sources, claims, research, and third-party material can each '
        'be flagged for a human decision with evidence. The available checks depend on what your manuscript needs.</p>'
        '<p class="help-step-outcome">A placeholder such as <code>[SCRIPTURE NEEDED]</code> remains a blocker '
        'until a person supplies and verifies an appropriate reference. The system does not invent one.</p></li>'
        '<li id="step-release"><div class="help-step-head"><span class="help-step-number">6</span>'
        '<div><p class="help-step-phase">Prepare</p><h3>Build and review the release packet</h3></div></div>'
        '<p>Choose <strong>Create Markdown build</strong> to assemble accepted chapters. Inspect the build and '
        'its blockers, then create a release candidate and export its review packet. The release review page '
        'shows the manuscript, provenance, findings, conditions, and consequences before a human decision.</p>'
        '<p class="help-step-outcome">A blocked build or candidate is for review, not publication. '
        'Final KDP upload and publication are separate manual actions.</p></li>'
        '</ol>'
        '<div class="help-two-up">'
        '<section class="help-note" id="costs"><h2>Before you use AI</h2>'
        '<p>Creating a book and saving an idea costs nothing in AI usage. A generation or analysis button '
        'sends context to your selected provider and may incur a charge. The form asks you to confirm each '
        'request. Your project spending limits are hard stops based on local estimates; the provider’s '
        'billing report is the final record of charges.</p></section>'
        '<section class="help-note" id="review"><h2>You stay in control</h2>'
        '<p>AI results are experimental. Open the review page to see the content, where it came from, '
        'findings, blockers, and conditions before accepting anything. Verification, rights, canon, and '
        'release decisions also require a person. Nothing is automatically published to KDP.</p></section></div>'
        '<section class="help-questions" id="questions"><h2>Common questions</h2>'
        '<details><summary>Where do I find the book I started?</summary><p>Return to the '
        '<a href="/">Workspace</a> home page. Open your project under <strong>Projects</strong>, '
        'then your book under <strong>Titles</strong>.</p></details>'
        '<details><summary>Why can’t I move to the next stage?</summary><p>Open the title page and '
        'check what is waiting in <strong>Awaiting acceptance</strong>, <strong>Verification</strong>, '
        'and the blocker lists. Review the required item or resolve the stated condition before trying again.</p></details>'
        '<details><summary>Can I fix a draft myself?</summary><p>Yes. Choose <strong>Edit in browser</strong> '
        'next to an experimental concept, plan item, or chapter. Saving creates a new version; the original '
        'remains available. Review and accept the version you want to keep.</p></details>'
        '<details><summary>Does a release packet publish my book?</summary><p>No. It gathers the manuscript '
        'and review evidence for a human decision. Uploading and publishing on KDP remain manual.</p></details>'
        '</section><div class="help-end"><p>Ready to begin?</p>'
        '<a class="help-primary" href="/#start">Create your book</a></div></div>'
    )
    return _page("Help: create a book", body, csrf_token=csrf_token)


def render_not_found(message: str = "Page not found") -> str:
    return _page("Not found", _empty_workspace(message))


def render_chapter_edit(title_id: str, asset_id: str, content: str, source_hash: str,
                        token: str, *, notice: str = "") -> str:
    body = (
        f'<p class="breadcrumb"><a href="/">Workspace</a> / <a href="{_e(_title_url(title_id))}">Title</a> / Edit chapter</p>'
        '<section class="title-section review-section"><h1>Edit experimental artefact</h1>'
        f'<p>Source {_e(asset_id)} · SHA-256 {_e(source_hash)}</p>'
        '<p>This creates a new experimental manual revision. It preserves the source, requires a separate human acceptance, and makes no provider call.</p>'
        + (f'<p class="action-notice action-error">{_e(notice)}</p>' if notice else '')
        +
        f'<form class="review-form" method="post" action="/titles/{_e(quote(title_id, safe=""))}/edit/{_e(quote(asset_id, safe=""))}">'
        f'<input type="hidden" name="csrf_token" value="{_e(token)}">'
        f'<input type="hidden" name="source_sha256" value="{_e(source_hash)}">'
        + _actor_field() +
        '<label>Reason for revision<textarea name="reason" required maxlength="2000" rows="2"></textarea></label>'
        f'<label>Complete revised content<textarea name="content" required maxlength="100000" rows="28">{_e(content)}</textarea></label>'
        '<button type="submit">Save experimental revision</button></form></section>'
    )
    return _page("Edit artefact", body, csrf_token=csrf_token)


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
            fields = (_actor_field("reviewer") +
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
    fields = _actor_field("reviewer")
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
    return _page(f'Review {kind}', body, csrf_token=csrf_token)


def _page(title: str, body: str, query: str = "", csrf_token: str = "") -> str:
    workspace_current = ' aria-current="page"' if title == "Workspace" else ""
    help_current = ' aria-current="page"' if title.startswith("Help:") else ""
    private_entry = title in {"Sign in", "Access setup"}
    logout = (f'<form method="post" action="/logout" class="logout-form">'
              f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
              '<button type="submit">Sign out</button></form>' if csrf_token and not private_entry else '')
    header_tools = ('' if private_entry else
        '<div class="header-tools"><nav class="site-nav" aria-label="Main navigation">'
        f'<a href="/"{workspace_current}>Workspace</a>'
        f'<a href="/help"{help_current}>Help</a>'
        '</nav><form action="/" method="get" role="search">'
        f'<label class="visually-hidden" for="workspace-search">Search projects and titles</label><input id="workspace-search" name="q" type="search" value="{_e(query)}" placeholder="Search projects and titles">'
        '<button type="submit">Search</button></form>'
        '<label class="theme-label" for="theme-choice">Theme</label><select id="theme-choice" name="theme" aria-label="Choose workspace theme">'
        '<option value="brand">Brand</option><option value="light">Light</option><option value="dark">Dark</option></select>'
        + logout + '</div>')
    footer_text = ('Access is limited to authorized operators.' if private_entry else
                   'SQLite remains the system of record. Actions require an explicit operator; this workspace cannot approve or publish.')
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
        + header_tools + '</header>'
        f'<main id="main">{body}</main>'
        '<footer class="app-footer"><span>Local operator workspace</span>'
        f'<span>{_e(footer_text)}</span></footer>'
        '</body></html>'
    )
