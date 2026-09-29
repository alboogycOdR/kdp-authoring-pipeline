from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, unquote, urlsplit
import re
import secrets

from kdp_pipeline.workspace.actions import ACTION_LABELS, run_action, run_release_check, run_review_decision
from kdp_pipeline.workspace.authoring import (AUTHORING_ACTIONS, create_book,
    create_manual_revision, read_edit_source, run_authoring_action, run_project_action)
from kdp_pipeline.workspace.inspection import inspect_workspace
from kdp_pipeline.workspace.render import (render_chapter_edit, render_not_found,
    render_help, render_review, render_title, render_workspace)
from kdp_pipeline.workspace.review import inspect_review


_ROUTE_ID = re.compile(r"^[A-Za-z0-9-]{1,80}$")
_STATIC_FILES = {
    "workspace.css": ("text/css; charset=utf-8", "static/workspace.css"),
    "workspace.js": ("text/javascript; charset=utf-8", "static/workspace.js"),
}


def create_workspace_server(root: Path, *, port: int = 8765) -> ThreadingHTTPServer:
    """Create a local Workspace server; mutations use existing audited services."""
    root = root.resolve()
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    csrf_token = secrets.token_urlsafe(32)
    flash: dict[str, str] = {}
    flash_lock = Lock()

    def save_notice(message: str) -> str:
        flash_id = secrets.token_urlsafe(16)
        with flash_lock:
            if len(flash) >= 100:
                flash.pop(next(iter(flash)))
            flash[flash_id] = message
        return flash_id

    def take_notice(flash_id: str) -> str:
        with flash_lock:
            return flash.pop(flash_id, "")

    class WorkspaceHandler(BaseHTTPRequestHandler):
        server_version = "KDPWorkspace"
        sys_version = ""

        def log_message(self, _format: str, *args: object) -> None:
            # Requests can contain locally entered search terms; do not log them.
            return

        def _respond(self, body: str | bytes, content_type: str, status: int = 200, *, head: bool = False) -> None:
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self'; script-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                             "form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            if not head:
                self.wfile.write(payload)

        def _snapshot(self) -> dict | None:
            try:
                return inspect_workspace(root)
            except FileNotFoundError:
                return None

        def _valid_host(self) -> bool:
            host = self.headers.get("Host", "").lower()
            return host in {f"127.0.0.1:{self.server.server_address[1]}",
                            f"localhost:{self.server.server_address[1]}"}

        def do_GET(self) -> None:
            if not self._valid_host():
                self._respond(render_not_found("This workspace accepts requests for localhost only."),
                              "text/html; charset=utf-8", 421)
                return
            parts = urlsplit(self.path)
            if parts.path.startswith("/static/"):
                name = parts.path.removeprefix("/static/")
                resource = _STATIC_FILES.get(name)
                if resource is None:
                    self._respond(render_not_found("Static resource not found."), "text/html; charset=utf-8", 404)
                    return
                content_type, relative = resource
                asset = files("kdp_pipeline.workspace").joinpath(*relative.split("/"))
                self._respond(asset.read_bytes(), content_type)
                return
            if parts.path == "/healthz":
                self._respond("ok", "text/plain; charset=utf-8")
                return
            if parts.path == "/help":
                self._respond(render_help(), "text/html; charset=utf-8")
                return
            try:
                query = parse_qs(parts.query, keep_blank_values=False, max_num_fields=8).get("q", [""])[0][:100]
            except ValueError:
                self._respond(render_not_found("Search query is too complex."), "text/html; charset=utf-8", 400)
                return
            if parts.path == "/":
                notice = take_notice(parse_qs(parts.query).get("result", [""])[0])
                self._respond(render_workspace(self._snapshot(), query=query,
                                               csrf_token=csrf_token, notice=notice), "text/html; charset=utf-8")
                return
            edit_match = re.fullmatch(r"/titles/([^/]+)/edit/([^/]+)", parts.path)
            if edit_match:
                title_id, asset_id = map(unquote, edit_match.groups())
                if not _ROUTE_ID.fullmatch(title_id) or not _ROUTE_ID.fullmatch(asset_id):
                    self._respond(render_not_found("Invalid chapter identifier."), "text/html; charset=utf-8", 400)
                    return
                try:
                    content, source_hash, _ = read_edit_source(root, title_id, asset_id)
                except (OSError, ValueError):
                    self._respond(render_not_found("Editable chapter not found or source integrity failed."),
                                  "text/html; charset=utf-8", 404)
                    return
                self._respond(render_chapter_edit(title_id, asset_id, content, source_hash, csrf_token),
                              "text/html; charset=utf-8")
                return
            review_match = re.fullmatch(r"/reviews/(asset|canon|release|verification|rights)/([^/]+)", parts.path)
            if review_match:
                kind, identifier = review_match.groups()
                identifier = unquote(identifier)
                if not _ROUTE_ID.fullmatch(identifier):
                    self._respond(render_not_found("Invalid review identifier."), "text/html; charset=utf-8", 400)
                    return
                try:
                    dossier = inspect_review(root, kind, identifier)
                except FileNotFoundError:
                    dossier = None
                if dossier is None:
                    self._respond(render_not_found("Review item was not found."), "text/html; charset=utf-8", 404)
                    return
                flash_id = parse_qs(parts.query).get("result", [""])[0]
                notice = take_notice(flash_id)
                self._respond(render_review(dossier, csrf_token, notice=notice), "text/html; charset=utf-8")
                return
            match = re.fullmatch(r"/(projects|titles)/([^/]+)", parts.path)
            if match:
                kind, raw_id = match.groups()
                identifier = unquote(raw_id)
                if not _ROUTE_ID.fullmatch(identifier):
                    self._respond(render_not_found("That identifier is not valid."), "text/html; charset=utf-8", 400)
                    return
                snapshot = self._snapshot()
                if kind == "titles" and snapshot is not None:
                    notice = parse_qs(parts.query).get("result", [""])[0]
                    message = take_notice(notice) or ACTION_LABELS.get(parse_qs(parts.query).get("done", [""])[0], "")
                    self._respond(render_title(snapshot, identifier, csrf_token=csrf_token, notice=message), "text/html; charset=utf-8",
                                  200 if identifier in snapshot["titles"] else 404)
                    return
                if kind == "projects":
                    if snapshot is None or not any(item["project_id"] == identifier for item in snapshot["projects"]):
                        self._respond(render_not_found(f"Project {identifier} was not found."), "text/html; charset=utf-8", 404)
                        return
                    notice = take_notice(parse_qs(parts.query).get("result", [""])[0])
                    self._respond(render_workspace(snapshot, project_id=identifier,
                        csrf_token=csrf_token, notice=notice), "text/html; charset=utf-8")
                    return
            self._respond(render_not_found(), "text/html; charset=utf-8", 404)

        def do_HEAD(self) -> None:
            if not self._valid_host():
                self._respond(render_not_found("This workspace accepts requests for localhost only."),
                              "text/html; charset=utf-8", 421, head=True)
                return
            parts = urlsplit(self.path)
            if parts.path == "/healthz":
                self._respond("ok", "text/plain; charset=utf-8", head=True)
            elif parts.path == "/help":
                self._respond(render_help(), "text/html; charset=utf-8", head=True)
            elif parts.path in {"/", "/projects", "/titles"}:
                self._respond(render_workspace(self._snapshot()), "text/html; charset=utf-8", head=True)
            else:
                self._respond(render_not_found(), "text/html; charset=utf-8", 404, head=True)

        def do_POST(self) -> None:
            if not self._valid_host():
                self._respond(render_not_found("This workspace accepts requests for localhost only."),
                              "text/html; charset=utf-8", 421)
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                self._respond(render_not_found("Request origin did not match this workspace."),
                              "text/html; charset=utf-8", 403)
                return
            path = urlsplit(self.path).path
            match = re.fullmatch(r"/titles/([^/]+)/actions/([a-z-]+)", path)
            project_match = re.fullmatch(r"/projects/([^/]+)/actions/(controls|new-title)", path)
            edit_match = re.fullmatch(r"/titles/([^/]+)/edit/([^/]+)", path)
            book_match = path == "/books"
            review_match = re.fullmatch(r"/reviews/(asset|canon|release|verification|rights)/([^/]+)/(decide|check)", path)
            if match is None and edit_match is None and review_match is None and project_match is None and not book_match:
                self._method_not_allowed()
                return
            if match:
                title_id, action = map(unquote, match.groups())
                valid_route = _ROUTE_ID.fullmatch(title_id) and action in (ACTION_LABELS.keys() | AUTHORING_ACTIONS)
            elif edit_match:
                title_id, asset_id = map(unquote, edit_match.groups())
                valid_route = _ROUTE_ID.fullmatch(title_id) and _ROUTE_ID.fullmatch(asset_id)
            elif project_match:
                project_id, project_action = map(unquote, project_match.groups())
                valid_route = _ROUTE_ID.fullmatch(project_id)
            elif book_match:
                valid_route = True
            else:
                kind, identifier, review_action = review_match.groups()
                identifier = unquote(identifier)
                valid_route = _ROUTE_ID.fullmatch(identifier) and (review_action != "check" or kind == "release")
            if not valid_route:
                self._respond(render_not_found(), "text/html; charset=utf-8", 404)
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
                self._respond(render_not_found("Submit a Workspace form to run this action."),
                              "text/html; charset=utf-8", 415)
                return
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError:
                size = -1
            if size < 0 or size > (200000 if edit_match else 16384):
                self._respond(render_not_found("Form size is invalid."), "text/html; charset=utf-8", 413)
                return
            try:
                values = parse_qs(self.rfile.read(size).decode("utf-8", errors="strict"),
                                  keep_blank_values=True, max_num_fields=24, strict_parsing=True)
                if any(len(items) != 1 for items in values.values()):
                    raise ValueError("Form contains duplicate fields.")
                form = {key: items[0] for key, items in values.items()}
            except (UnicodeDecodeError, ValueError):
                self._respond(render_not_found("Form data is invalid."), "text/html; charset=utf-8", 400)
                return
            if not secrets.compare_digest(form.get("csrf_token", ""), csrf_token):
                self._respond(render_not_found("Reload the Workspace and submit the form again."),
                              "text/html; charset=utf-8", 403)
                return
            if edit_match:
                try:
                    result = create_manual_revision(root, title_id, asset_id, form)
                except (OSError, ValueError) as exc:
                    try:
                        content, source_hash, _ = read_edit_source(root, title_id, asset_id)
                    except (OSError, ValueError):
                        self._respond(render_not_found("Chapter source changed or is unavailable."),
                                      "text/html; charset=utf-8", 409)
                        return
                    self._respond(render_chapter_edit(title_id, asset_id, content, source_hash,
                        csrf_token, notice=str(exc) if isinstance(exc, ValueError) else "Revision could not be saved."),
                        "text/html; charset=utf-8", 422)
                    return
                flash_id = save_notice(result)
                self.send_response(303)
                self.send_header("Location", f"/titles/{title_id}?result={flash_id}#pending")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if book_match or project_match:
                try:
                    if book_match:
                        destination_id, message = create_book(root, form)
                        location = f"/titles/{destination_id}"
                    else:
                        destination_id, message = run_project_action(root, project_id, project_action, form)
                        location = f"/titles/{destination_id}" if destination_id else f"/projects/{project_id}"
                except (OSError, ValueError, RuntimeError) as exc:
                    snapshot = self._snapshot()
                    message = str(exc) if isinstance(exc, ValueError) else "Action failed; inspect the current records."
                    self._respond(render_workspace(snapshot, project_id=project_id if project_match else None,
                        csrf_token=csrf_token, notice=message, error=True), "text/html; charset=utf-8", 422)
                    return
                flash_id = save_notice(message)
                self.send_response(303)
                self.send_header("Location", f"{location}?result={flash_id}")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if review_match:
                try:
                    title_id, result = (run_release_check(root, identifier, form) if review_action == "check"
                                        else run_review_decision(root, kind, identifier, form))
                except (OSError, ValueError) as exc:
                    dossier = inspect_review(root, kind, identifier)
                    if dossier is None:
                        self._respond(render_not_found("Review item was not found."),
                                      "text/html; charset=utf-8", 404)
                        return
                    message = str(exc) if isinstance(exc, ValueError) else "Decision failed; inspect the current record."
                    self._respond(render_review(dossier, csrf_token, notice=message, error=True),
                                  "text/html; charset=utf-8", 422)
                    return
                flash_id = save_notice(result)
                self.send_response(303)
                self.send_header("Location", f"/reviews/{kind}/{identifier}?result={flash_id}")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            try:
                result = (run_authoring_action(root, title_id, action, form)
                          if action in AUTHORING_ACTIONS else run_action(root, title_id, action, form))
            except (OSError, ValueError, RuntimeError) as exc:
                snapshot = self._snapshot()
                if snapshot is None:
                    self._respond(render_not_found("Workspace database is unavailable."),
                                  "text/html; charset=utf-8", 503)
                    return
                message = str(exc) if isinstance(exc, ValueError) else "Action failed; inspect the title and local files."
                self._respond(render_title(snapshot, title_id, csrf_token=csrf_token,
                                           notice=message, error=True), "text/html; charset=utf-8", 422)
                return
            self.send_response(303)
            if action in AUTHORING_ACTIONS:
                flash_id = save_notice(result)
                self.send_header("Location", f"/titles/{title_id}?result={flash_id}#authoring")
            else:
                self.send_header("Location", f"/titles/{title_id}?done={action}#actions")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _method_not_allowed(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed

    server = ThreadingHTTPServer(("127.0.0.1", port), WorkspaceHandler)
    server.daemon_threads = True
    return server


def serve_workspace(root: Path, *, port: int = 8765) -> None:
    server = create_workspace_server(root, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
