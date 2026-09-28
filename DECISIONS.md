# Architecture Decisions

This is the repository landing page for Architecture Decision Records (ADRs). The records live in [`KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/07_Architecture_Decision_Records/`](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/07_Architecture_Decision_Records/). Add future decisions there using the project's ADR conventions; this page should remain an index rather than a second decision store.

## Accepted direction

The current accepted architectural direction is established by [ADR-0001: System Vision](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/07_Architecture_Decision_Records/ADR-0001-System-Vision.md), the [Master Architecture Overview](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/01_Architecture/MASTER_ARCHITECTURE_OVERVIEW.md), and the detailed v1.0 build baseline. Major decisions and constraints include:

- **Local-first system:** authoring and operational state run in the local project environment.
- **SQLite is authoritative:** files are durable artefacts and synchronized snapshots, not a competing operational database.
- **Human approval gates:** acceptance, canon mutation, and release review require explicit human decisions.
- **Replaceable providers:** model providers are adapters, not workflow-defining dependencies.
- **Experimental versus accepted artefacts:** generated output remains experimental until accepted with traceable provenance.
- **Audit and provenance first:** workflow mutations and accepted assets retain their history and lineage.
- **No autonomous publishing:** KDP publication remains a human-controlled action; no KDP upload automation is part of the accepted baseline.
- **No secret persistence:** credentials and sensitive KDP account information must not be stored in project artefacts, logs, or AI context.

Only ADR-0001 is currently present in the ADR directory. The bullets above summarize the accepted baseline; they are not separate ADR records. See [ARCHITECTURE.md](ARCHITECTURE.md) for the documentation hierarchy and [docs/ARCHITECTURE_INDEX.md](docs/ARCHITECTURE_INDEX.md) for related references.
