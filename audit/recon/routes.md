# Workspace route × method table (static trace, `src/kdp_pipeline/workspace/server.py` @ 91c48ad)

All routes: `Host` must equal `127.0.0.1:<port>` or `localhost:<port>` (else 421, `server.py:79-82`). No route requires authentication; no session or user identity exists. "Operator"/"reviewer" is a form field (`actions.py:36`, `authoring.py:247`).

| Method | Path | Handler / service | CSRF token | Origin check | Body cap | Mutates | Notes |
|---|---|---|---|---|---|---|---|
| GET | `/static/workspace.css`, `/static/workspace.js` | package resource | – | – | – | no | fixed allow-list |
| GET | `/healthz` | literal `ok` | – | – | – | no | never touches DB/disk (`server.py:100`) |
| GET | `/help` | `render_help` | – | – | – | no | |
| GET | `/` `?q=&result=` | `inspect_workspace` → full snapshot of every title | page embeds token | – | – | no (runs `init_db` DDL checks via `session_scope`) | O(titles) cost per request |
| GET | `/projects/<id>` | snapshot + project forms | embeds token | – | – | no | `_ROUTE_ID` after `unquote` |
| GET | `/titles/<id>` `?result=&done=` | snapshot + title forms | embeds token | – | – | no | |
| GET | `/titles/<id>/edit/<asset>` | `read_edit_source` | embeds token | – | – | no | ≤100 000-byte source |
| GET | `/reviews/{asset,canon,release,verification,rights}/<id>` | `inspect_review` | embeds token + `review_hash` | – | – | no | |
| HEAD | `/`, `/projects`, `/titles`, `/help`, `/healthz` | render without token | – | – | – | no | diverges from GET for other paths (404) |
| POST | `/books` | `create_book` → project, budget, title, idea note, concept gate | required | `Origin` compared **only if present** (`server.py:193-197`) | 16 KiB | yes | |
| POST | `/projects/<id>/actions/controls` | select provider + set hard budget | required | if present | 16 KiB | yes | can raise limits to $10 000 |
| POST | `/projects/<id>/actions/new-title` | `create_title` | required | if present | 16 KiB | yes | |
| POST | `/titles/<id>/actions/<action>` | 9 workflow actions (`actions.py:23`) + 21 authoring actions (`authoring.py:236-244`), 14 of which call the provider | required | if present | 16 KiB | yes | generation needs `confirm_cost=yes` (not bound to an estimate) |
| POST | `/titles/<id>/edit/<asset>` | `create_manual_revision` | required | if present | 200 000 B | yes | content ≤100 000 chars, stripped |
| POST | `/reviews/<kind>/<id>/decide` | `run_review_decision` → accept asset / canon / release / verification / rights | required + fresh `review_hash` + `confirm_consequences=yes` | if present | 16 KiB | yes | "human approval gate" |
| POST | `/reviews/release/<id>/check` | `record_candidate_check` | required + `review_hash` | if present | 16 KiB | yes | |
| PUT/PATCH/DELETE | any | 405 | – | – | – | no | 405/303 responses omit security headers |
| OPTIONS/TRACE/other | any | stdlib 501 | – | – | – | no | |

Server properties: `ThreadingHTTPServer`, one thread per connection, `daemon_threads=True`, no socket timeout set on the handler (`BaseHTTPRequestHandler.timeout` is `None`), `log_message` suppressed (no access log), uncaught non-`ValueError/OSError/RuntimeError` exceptions (e.g. `sqlalchemy.exc.OperationalError: database is locked`) propagate out of the handler, so the client gets a dropped connection and the traceback goes to stderr.

CSRF token: one `secrets.token_urlsafe(32)` per process (`server.py:32`), identical for all clients and all forms, valid until restart, embedded in every GET page. It protects against cross-site form posts from origins that cannot read the page. It is not an authentication or authorisation mechanism.
