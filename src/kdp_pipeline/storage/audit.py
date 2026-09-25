from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.db import AuditEventRow, utcnow


class AuditEventWriter:
    """Application-level append-only writer; no update/delete API is exposed."""

    @staticmethod
    def append(
        session,
        *,
        actor_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        correlation_id: str,
        result: str,
        before_hash: str | None = None,
        after_hash: str | None = None,
        metadata: dict | None = None,
        timestamp_utc: datetime | None = None,
    ) -> AuditEventRow:
        event = AuditEventRow(
            event_id=new_id("EVT"),
            timestamp_utc=timestamp_utc or utcnow(),
            actor_type="human" if actor_id != "system" else "system",
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_hash=before_hash,
            after_hash=after_hash,
            correlation_id=correlation_id,
            result=result,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
        )
        session.add(event)
        return event


def list_events(session, entity_id: str) -> list[AuditEventRow]:
    stmt = select(AuditEventRow).where(AuditEventRow.entity_id == entity_id).order_by(
        AuditEventRow.timestamp_utc, AuditEventRow.event_id
    )
    return list(session.scalars(stmt))
