# ADR 0004: Human review preserves AI output

## Status

Accepted (2026-06-05)

## Context

Compliance teams need human judgment without losing the original AI recommendation for audit trails.

## Decision

- Store `ai_status` immutably on the audit record
- Human overrides write to `review_decisions` and update `final_status` only
- API returns both AI and final status

## Consequences

- Disputes can compare AI vs human decision
- Read only users can view history but not override
