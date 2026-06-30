# ADR 0003: Azure PostgreSQL as audit of record

## Status

Accepted (2026-06-05)

## Context

Portfolio deployments stored no audit history. Internal teams require traceability: who audited which ad, when, and what changed after human review.

## Decision

Use Azure Database for PostgreSQL as the system of record for teams, users, audits, violations, reviews, and policy versions. Azure AI Search remains the vector store for policy chunks only.

## Consequences

- Requires `DATABASE_URL` and Alembic migrations in CI/CD
- Container Apps must reach Postgres over private networking or firewall rules
- Search index and relational audit data can drift; policy version ids link them
