# Data flow, trust boundaries and mutation entry points

## Data flow (operator input → release)

```mermaid
flowchart LR
  OP[Operator / any reachable client] -->|form fields: name, idea, audience, notes| WS[Workspace server]
  CLI[CLI user] --> SVC
  WS --> SVC[Domain services]
  SVC -->|render prompt template from prompts/ on disk| PR[Prompt registry]
  PR --> GEN[GenerationService]
  GEN -->|budget check + reservation| DB[(SQLite .kdp/state.db)]
  GEN -->|HTTPS/HTTP POST, Bearer = os.getenv(profile.api_key_env)| PROV[Provider base_url]
  PROV -->|text, usage, usage.cost| GEN
  GEN -->|usage event, job, asset row, provenance row| DB
  GEN -->|05_drafts/experimental/*.md| FS[(projects/ files)]
  SVC -->|acceptance: copy file, approval row| FS
  SVC -->|build: concatenate accepted chapters| FS
  CANON[06_canon/*.json on disk] -->|read without DB hash| SVC
  SVC -->|release candidate freeze, packet JSON| FS
  FS -->|manual| KDP[Human uploads to KDP]
```

## What each generation request actually contains (verified with `CaptureProvider`, tests `KDP-AUD-005/006`)

| Family | Prompt variables sent | Context the manifest/provenance claims | Gap |
|---|---|---|---|
| concept/audience-brief | audience + operator idea note | idea note | none |
| concept/generate-seeds, enrich, score, drafting-brief | source concept text | source concept | none |
| planning/positioning, book-brief, outline, chapter-card | working title, title id, `target_reader` (always "unspecified"), chapter number | nothing (empty manifest) | **accepted concept brief, idea note and earlier planning never sent**; honest manifest, blind generation (AUD-006) |
| drafting/chapter-draft, chapter-revise | accepted card, positioning, brief, outline, prior summaries, (revise: source draft + findings) | same | consistent |
| continuity | draft + 4 planning artefacts + canon JSON files | same | canon files unverified against DB (AUD-012) |
| editorial/developmental | working title, title id, chapter number only | **source chapter + planning assets** | **manifest claims inputs never sent** (AUD-005) |
| editorial/voice, line, copy, reader-experience, consistency | full chapter context | same | consistent |

## Trust boundaries

1. **Network → Workspace.** No authentication; trust rests on loopback binding (dev) or tailnet ACLs + Caddy (staging). Anyone who can load a page can act as any "operator".
2. **Workspace/CLI → provider.** Unpublished manuscript text, planning, canon and operator free text leave the machine. The destination and the credential variable are whatever the profile says.
3. **Provider → pipeline.** Model text is untrusted: rendered with HTML escaping (held) but stored, re-fed into later prompts (findings, summaries), and accepted without finish-reason checks.
4. **Filesystem ↔ SQLite.** Absolute paths and SHA-256 in DB; canon JSON and prompts are read from disk without DB-anchored hashes.
5. **OS account.** Anyone with the service account can edit SQLite (including `audit_events`) with no tamper evidence.

## Mutation entry points and the invariant checks each enforces

| Mutation | CLI | Workspace | Checks enforced in the service (both paths) | Checks only in one path |
|---|---|---|---|---|
| Title transition | `kdp transition` (any legal edge) | only advance-validated/planned/drafting | legal edge; PLANNED requires accepted planning | Workspace exposes fewer edges; CLI can reach PREFLIGHT_PASSED/KDP_DRAFT_READY ungated (AUD-003) |
| Generation (14 kinds) | `positioning create`, `chapter draft`, … | authoring actions | budget hard-stop/per-run, pricing when hard-stop | `confirm_cost`, named operator, priced+keyed profile, hard-stop budget required **only** in Workspace |
| Asset acceptance | `planning accept`, `chapter accept --reviewer`, `concept approve` | review decide | experimental, hash, provenance | Workspace derives chapter number from filename and adds scripture condition; CLI takes any chapter number (AUD-016) |
| Canon decision | `canon approve` | review decide | status=proposed | Workspace blocks proposals from invalid analysis; CLI does not |
| Verification / rights decision | `verify decide`, `rights decide` | review decide | evidence rules | – |
| Release check / review / packet | `release check/review/packet` | review check/decide, export-packet | blockers recomputed | Workspace requires `review_hash` freshness |
| Provider profile create/enable | `providers add-*`, `enable`, `disable`, `set-timeouts` | not exposed (select + budget only) | pydantic settings validation | – |
| Budget | `budget set` (can set `--soft`, remove caps) | `controls` (always hard-stop, ≤ $10 000) | limits > 0 | – |
| Manual revision | none | edit form | source hash, title state | Workspace-only |
| Front/back matter | `build matter-add SOURCE_FILE` (reads any path) | none | – | – |
