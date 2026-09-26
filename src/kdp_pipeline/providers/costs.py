from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from sqlalchemy import select

from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.db import (
    BudgetReservationRow,
    ModelPricingRow,
    ProjectBudgetRow,
    ProviderProfileRow,
    ProjectRow,
    UsageEventRow,
    utcnow,
)


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def estimate_run_cost(pricing: ModelPricingRow | None, system_instructions: str,
                      rendered_prompt: str, max_output_tokens: int) -> tuple[float | None, str | None]:
    if pricing is None:
        return None, None
    # UTF-8 bytes are used as a conservative, provider-neutral preflight token bound.
    input_token_bound = len((system_instructions + "\n" + rendered_prompt).encode("utf-8"))
    cost = (input_token_bound * pricing.input_usd_per_million
            + max_output_tokens * pricing.output_usd_per_million) / 1_000_000
    return cost, pricing.currency


def evaluate_and_reserve(session, *, project_id: str, job_id: str, pricing: ModelPricingRow | None,
                         system_instructions: str, rendered_prompt: str, max_output_tokens: int,
                         now: datetime | None = None) -> dict[str, Any]:
    """Check project caps and add one small per-run reservation when a budget is configured."""
    budget = session.get(ProjectBudgetRow, project_id)
    estimate, currency = estimate_run_cost(pricing, system_instructions, rendered_prompt, max_output_tokens)
    if budget is None:
        return {"estimate": estimate, "currency": currency, "warning": None,
                "blocked": None, "reservation": None}

    has_limits = budget.monthly_limit_usd is not None or budget.max_run_estimated_cost_usd is not None
    if not has_limits:
        return {"estimate": estimate, "currency": currency, "warning": None,
                "blocked": None, "reservation": None}
    if estimate is None and budget.hard_stop:
        return {"estimate": None, "currency": None, "warning": None,
                "blocked": "Hard-stop budget requires pricing for this provider/model; generation was not started",
                "reservation": None}

    warnings: list[str] = []
    if estimate is None:
        warnings.append("Cost is unpriced; configure model pricing or use a soft budget")
    month = current_month(now)
    usage_rows = session.scalars(select(UsageEventRow).where(
        UsageEventRow.project_id == project_id
    )).all()
    spent = sum(row.estimated_cost or 0.0 for row in usage_rows
                if row.created_at.strftime("%Y-%m") == month and row.currency == "USD")
    reservation_rows = session.scalars(select(BudgetReservationRow).where(
        BudgetReservationRow.project_id == project_id,
        BudgetReservationRow.status.in_(("reserved", "uncertain", "unpriced")),
    )).all()
    reserved = sum(row.estimated_cost_usd or 0.0 for row in reservation_rows if row.month == month)
    projected = spent + reserved + (estimate or 0.0)

    if estimate is not None and budget.max_run_estimated_cost_usd is not None:
        if estimate > budget.max_run_estimated_cost_usd:
            message = (f"Estimated run cost ${estimate:.6f} exceeds the project per-run limit "
                       f"${budget.max_run_estimated_cost_usd:.6f}")
            if budget.hard_stop:
                return {"estimate": estimate, "currency": currency, "warning": None,
                        "blocked": message, "reservation": None}
            warnings.append(message)

    if estimate is not None and budget.monthly_limit_usd is not None:
        if projected > budget.monthly_limit_usd and budget.hard_stop:
            return {"estimate": estimate, "currency": currency, "warning": None,
                    "blocked": (f"Project monthly budget would be exceeded: projected ${projected:.6f}; "
                                f"limit ${budget.monthly_limit_usd:.6f}"), "reservation": None}
    if (budget.monthly_limit_usd is not None
            and projected >= budget.monthly_limit_usd * budget.warning_percent / 100):
        warnings.append(f"Project monthly budget warning threshold ({budget.warning_percent}%) reached")

    reservation = BudgetReservationRow(
        reservation_id=new_id("BRS"), job_id=job_id, project_id=project_id,
        month=month, estimated_cost_usd=estimate,
        status="reserved" if estimate is not None else "unpriced", created_at=utcnow(),
    )
    session.add(reservation)
    return {"estimate": estimate, "currency": currency,
            "warning": "; ".join(warnings) if warnings else None,
            "blocked": None, "reservation": reservation}


def calculate_usage_cost(usage, pricing: ModelPricingRow | None) -> dict[str, Any]:
    """Return token/cost values without inventing unavailable usage or pricing."""
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None,
                "cached_input_tokens": None, "estimated_cost": None,
                "currency": None, "source": "unknown",
                "cost_details": {"basis": "unknown", "reason": "provider usage metadata unavailable"}}
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    cached_tokens = usage.cached_input_tokens
    cost = None
    currency = usage.currency
    source = "unknown"
    cost_details: dict[str, Any] = {"basis": "unknown", "reason": "no provider cost or configured pricing"}
    if usage.reported_cost is not None:
        cost, source = usage.reported_cost, "provider_reported"
        cost_details = {"basis": "provider_reported"}
    elif usage.estimated_cost is not None:
        cost, source = usage.estimated_cost, "estimated"
        cost_details = {"basis": "provider_estimate"}
    elif (pricing is not None and input_tokens is not None and output_tokens is not None):
        cached = min(cached_tokens or 0, input_tokens)
        uncached = input_tokens - cached
        cached_rate = (pricing.cached_input_usd_per_million
                       if pricing.cached_input_usd_per_million is not None
                       else pricing.input_usd_per_million)
        cost = (uncached * pricing.input_usd_per_million
                + cached * cached_rate
                + output_tokens * pricing.output_usd_per_million) / 1_000_000
        source = "estimated"
        cost_details = {"basis": "configured_model_rates", "provider_id": pricing.provider_id,
                        "model": pricing.model,
                        "input_usd_per_million": pricing.input_usd_per_million,
                        "output_usd_per_million": pricing.output_usd_per_million,
                        "cached_input_usd_per_million": pricing.cached_input_usd_per_million,
                        "currency": pricing.currency, "pricing_updated_at": pricing.updated_at.isoformat()}
    if currency is None and (source == "estimated" or source == "provider_reported"):
        currency = pricing.currency if pricing is not None else "USD"
    if cost is not None and (not isfinite(float(cost)) or cost < 0):
        cost, source, currency = None, "unknown", None
        cost_details = {"basis": "unknown", "reason": "invalid provider cost value"}
    if currency is not None:
        currency = currency.upper()
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": usage.total_tokens, "cached_input_tokens": cached_tokens,
            "estimated_cost": float(cost) if cost is not None else None,
            "currency": currency, "source": source, "cost_details": cost_details}


def settle_reservation(session, job_id: str, cost: float | None) -> None:
    reservation = session.scalar(select(BudgetReservationRow).where(
        BudgetReservationRow.job_id == job_id
    ))
    if reservation is None:
        return
    reservation.status = "settled" if cost is not None else "unpriced"
    reservation.settled_at = utcnow()


def mark_reservation_uncertain(session, job_id: str) -> None:
    reservation = session.scalar(select(BudgetReservationRow).where(
        BudgetReservationRow.job_id == job_id
    ))
    if reservation is not None and reservation.status == "reserved":
        reservation.status = "uncertain"


def set_model_pricing(root, provider_id: str, model: str, *, input_usd_per_million: float,
                      output_usd_per_million: float, cached_input_usd_per_million: float | None = None,
                      currency: str = "USD") -> dict[str, Any]:
    import math
    from kdp_pipeline.storage.audit import AuditEventWriter
    from kdp_pipeline.storage.service import session_scope

    for label, value in (("input", input_usd_per_million), ("output", output_usd_per_million),
                         ("cached input", cached_input_usd_per_million)):
        if value is not None and (not math.isfinite(float(value)) or value < 0):
            raise ValueError(f"{label.title()} price must be finite and non-negative")
    if currency.upper() != "USD":
        raise ValueError("Configured per-token pricing and project budgets are denominated in USD")
    with session_scope(root) as session:
        if session.get(ProviderProfileRow, provider_id) is None:
            raise ValueError(f"Unknown provider profile: {provider_id}")
        row = session.get(ModelPricingRow, (provider_id, model))
        before = ({"input": row.input_usd_per_million, "output": row.output_usd_per_million,
                   "cached_input": row.cached_input_usd_per_million, "currency": row.currency}
                  if row else None)
        if row is None:
            row = ModelPricingRow(provider_id=provider_id, model=model,
                                  input_usd_per_million=input_usd_per_million,
                                  output_usd_per_million=output_usd_per_million,
                                  cached_input_usd_per_million=cached_input_usd_per_million,
                                  currency=currency.upper(), updated_at=utcnow())
            session.add(row)
        else:
            row.input_usd_per_million = input_usd_per_million
            row.output_usd_per_million = output_usd_per_million
            row.cached_input_usd_per_million = cached_input_usd_per_million
            row.currency = currency.upper()
            row.updated_at = utcnow()
        AuditEventWriter.append(session, actor_id="operator", action="pricing.model.configured",
                                entity_type="provider_profile", entity_id=provider_id,
                                correlation_id=provider_id, result="success",
                                metadata={"model": model, "before": before,
                                          "after": {"input": input_usd_per_million,
                                                    "output": output_usd_per_million,
                                                    "cached_input": cached_input_usd_per_million,
                                                    "currency": currency.upper()}})
        session.commit()
        return {"provider_id": provider_id, "model": model,
                "input_usd_per_million": row.input_usd_per_million,
                "output_usd_per_million": row.output_usd_per_million,
                "cached_input_usd_per_million": row.cached_input_usd_per_million,
                "currency": row.currency}


def list_model_pricing(root, provider_id: str | None = None) -> list[dict[str, Any]]:
    from kdp_pipeline.storage.service import session_scope
    with session_scope(root) as session:
        query = select(ModelPricingRow)
        if provider_id:
            query = query.where(ModelPricingRow.provider_id == provider_id)
        rows = session.scalars(query.order_by(ModelPricingRow.provider_id, ModelPricingRow.model)).all()
        return [{"provider_id": row.provider_id, "model": row.model,
                 "input_usd_per_million": row.input_usd_per_million,
                 "output_usd_per_million": row.output_usd_per_million,
                 "cached_input_usd_per_million": row.cached_input_usd_per_million,
                 "currency": row.currency, "updated_at": row.updated_at.isoformat()} for row in rows]


def set_project_budget(root, project_id: str, *, monthly_limit_usd: float | None,
                       max_run_estimated_cost_usd: float | None, warning_percent: int,
                       hard_stop: bool) -> dict[str, Any]:
    import math
    from kdp_pipeline.storage.audit import AuditEventWriter
    from kdp_pipeline.storage.service import session_scope

    if monthly_limit_usd is None and max_run_estimated_cost_usd is None:
        raise ValueError("Set a monthly limit or a per-run estimated-cost limit")
    for label, value in (("monthly", monthly_limit_usd), ("per-run", max_run_estimated_cost_usd)):
        if value is not None and (not math.isfinite(float(value)) or value <= 0):
            raise ValueError(f"{label.title()} budget limit must be finite and greater than zero")
    if not 1 <= warning_percent <= 100:
        raise ValueError("Warning percent must be between 1 and 100")
    with session_scope(root) as session:
        if session.get(ProjectRow, project_id) is None:
            raise ValueError(f"Unknown project: {project_id}")
        row = session.get(ProjectBudgetRow, project_id)
        before = ({"monthly_limit_usd": row.monthly_limit_usd,
                   "max_run_estimated_cost_usd": row.max_run_estimated_cost_usd,
                   "warning_percent": row.warning_percent, "hard_stop": row.hard_stop}
                  if row else None)
        if row is None:
            row = ProjectBudgetRow(project_id=project_id, updated_at=utcnow())
            session.add(row)
        row.monthly_limit_usd = monthly_limit_usd
        row.max_run_estimated_cost_usd = max_run_estimated_cost_usd
        row.warning_percent = warning_percent
        row.hard_stop = hard_stop
        row.updated_at = utcnow()
        AuditEventWriter.append(session, actor_id="operator", action="budget.policy.configured",
                                entity_type="project", entity_id=project_id,
                                correlation_id=project_id, result="success",
                                metadata={"before": before, "after": {
                                    "monthly_limit_usd": monthly_limit_usd,
                                    "max_run_estimated_cost_usd": max_run_estimated_cost_usd,
                                    "warning_percent": warning_percent, "hard_stop": hard_stop}})
        session.commit()
    return project_budget_report(root, project_id)


def project_budget_report(root, project_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    from kdp_pipeline.storage.service import session_scope
    month = current_month(now)
    with session_scope(root) as session:
        budget = session.get(ProjectBudgetRow, project_id)
        if budget is None:
            return {"project_id": project_id, "configured": False, "month": month,
                    "spent_usd": 0.0, "reserved_usd": 0.0, "unknown_cost_events": 0,
                    "warning": None}
        events = session.scalars(select(UsageEventRow).where(UsageEventRow.project_id == project_id)).all()
        monthly = [event for event in events if event.created_at.strftime("%Y-%m") == month]
        spent = sum(event.estimated_cost or 0.0 for event in monthly if event.currency == "USD")
        reservations = session.scalars(select(BudgetReservationRow).where(
            BudgetReservationRow.project_id == project_id,
            BudgetReservationRow.month == month,
            BudgetReservationRow.status.in_(("reserved", "uncertain", "unpriced")),
        )).all()
        reserved = sum(row.estimated_cost_usd or 0.0 for row in reservations)
        total = spent + reserved
        warning = None
        if budget.monthly_limit_usd is not None and total >= budget.monthly_limit_usd * budget.warning_percent / 100:
            warning = f"Monthly budget warning threshold ({budget.warning_percent}%) reached"
        if any(event.source == "unknown" or (event.estimated_cost is not None and event.currency != "USD") for event in monthly):
            warning = (warning + "; " if warning else "") + "Some generation usage is unpriced"
        return {"project_id": project_id, "configured": True, "month": month,
                "monthly_limit_usd": budget.monthly_limit_usd,
                "max_run_estimated_cost_usd": budget.max_run_estimated_cost_usd,
                "warning_percent": budget.warning_percent, "hard_stop": budget.hard_stop,
                "spent_usd": round(spent, 8), "reserved_usd": round(reserved, 8),
                "remaining_usd": round(max(0.0, budget.monthly_limit_usd - total), 8)
                if budget.monthly_limit_usd is not None else None,
                "unknown_cost_events": sum(event.source == "unknown" or
                                           (event.estimated_cost is not None and event.currency != "USD")
                                           for event in monthly),
                "warning": warning,
                "reservations": [{"reservation_id": row.reservation_id, "job_id": row.job_id,
                                  "estimated_cost_usd": row.estimated_cost_usd,
                                  "status": row.status} for row in reservations]}
