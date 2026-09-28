# Sprint 14–16 Frontend Track Specification

This package contains the implementation specification for:
- Sprint 14 — Interactive Operator Frontend Foundation
- Sprint 15 — Frontend Workflow Actions
- Sprint 16 — Frontend Review & Approval UX

Core principles:
- Local-first web UI.
- SQLite remains authoritative.
- Existing audited backend services remain the only mutation path.
- No secrets displayed.
- No automatic AI approvals.
- No KDP upload/publication automation.

Sprint 14:
- Read-only operator dashboard
- Project/title pages
- Provider/budget/verification/build/release views
- Local server (127.0.0.1)

Sprint 15:
- Safe workflow actions (verification, builds, release-candidate creation, queue management)
- All actions call existing audited services.

Sprint 16:
- Human review/approval UX
- Approval queues
- Conditions on approvals
- Canon/release decisions remain human-controlled.
