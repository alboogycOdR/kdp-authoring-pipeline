# KDP Pipeline Master Architecture Pack

This package is the long-term architecture source of truth for the KDP Authoring Pipeline. Repository-wide precedence and agent boundaries are defined in [AGENTS.md](../AGENTS.md). The repository [architecture index](../docs/ARCHITECTURE_INDEX.md) links the pack to detailed architecture, operations, ADRs, and reports.

## Structure

The directories below define the intended package layout. Only `01_Architecture` and `07_Architecture_Decision_Records` currently contain documents; the other directories are reserved for roadmap, handover, runbook, and pilot materials as they are added.

- [01_Architecture](01_Architecture/)
  - [Master Architecture Overview](01_Architecture/MASTER_ARCHITECTURE_OVERVIEW.md)
- [02_Sprints_1_13_Core](02_Sprints_1_13_Core/) — reserved; no files yet
- [03_Sprints_14_16_Frontend](03_Sprints_14_16_Frontend/) — reserved; no files yet
- [04_Codex_Handover_Prompts](04_Codex_Handover_Prompts/) — reserved; no files yet
- [05_Operational_Runbooks](05_Operational_Runbooks/) — reserved; no files yet
- [06_Pilot_Reports](06_Pilot_Reports/) — reserved; no files yet
- [07_Architecture_Decision_Records](07_Architecture_Decision_Records/)
  - [ADR-0001: System Vision](07_Architecture_Decision_Records/ADR-0001-System-Vision.md)

## Intended use

Use the pack for architectural decisions, onboarding, reviews, and long-term maintenance. Keep operational how-to guidance in `docs/operations/` and link to it from the [architecture index](../docs/ARCHITECTURE_INDEX.md) rather than copying it into this pack.
