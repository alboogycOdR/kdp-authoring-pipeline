# KDP Pipeline pilot workflow

This runbook covers the current deterministic, single-chapter pilot. It uses `FakeProvider` and makes no external API calls.

## Environment

Use Python 3.12 from `.venv` and verify the CLI:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\kdp.exe --help
.\.venv\Scripts\kdp.exe doctor
```

`kdp doctor` is read-only. It reports problems and recommended human action; it does not repair them.

## Operator workflow

Create a project and title:

```powershell
kdp init-project "Pilot Project"
kdp new-title PROJECT_ID "Pilot Title"
```

Generate and explicitly accept the four planning artefacts, then advance the title:

```text
kdp positioning create TITLE_ID
kdp brief create TITLE_ID
kdp outline generate TITLE_ID
kdp chapter-card generate TITLE_ID --chapter-number 1
kdp planning accept ASSET_ID --reviewer REVIEWER
kdp planning advance-validated TITLE_ID
kdp planning advance-planned TITLE_ID
```

Advance into drafting explicitly and run the chapter lifecycle:

```text
kdp chapter advance-drafting TITLE_ID
kdp chapter draft TITLE_ID 1
kdp chapter continuity TITLE_ID 1 --asset-id DRAFT_ASSET_ID
kdp editorial run TITLE_ID 1 --pass developmental --asset-id DRAFT_ASSET_ID
kdp chapter revise TITLE_ID 1 --asset-id DRAFT_ASSET_ID
kdp chapter accept TITLE_ID 1 --asset-id REVISION_ASSET_ID --reviewer REVIEWER
```

Continuity proposals are proposals only. Canon entities, timelines, and world rules are not automatically changed.

## Inspection

All inspection commands are read-only:

```text
kdp inspect title TITLE_ID
kdp inspect lifecycle TITLE_ID
kdp inspect assets TITLE_ID
kdp inspect jobs TITLE_ID
kdp inspect provenance TITLE_ID
kdp audit TITLE_ID
kdp canon proposals TITLE_ID
```

Reports identify state, planning completeness, chapter assets, jobs, provenance, approvals, findings, proposals, audit history, and file/hash inconsistencies.

## Deterministic dry run

Run the complete isolated pilot without API keys:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_dry_run.py
```

The default workspace is temporary and is removed after the process exits. To use an explicit workspace, pass `--root`; this intentionally creates project state there.

Repeated acceptance of the same experimental source is idempotent when the accepted file, hash, approval, and provenance agree. Conflicting accepted content is rejected rather than overwritten.
