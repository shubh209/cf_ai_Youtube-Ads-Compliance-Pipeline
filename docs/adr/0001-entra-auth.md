# ADR 0001: Microsoft Entra ID for internal authentication

## Status

Accepted (2026-06-05)

## Context

The compliance tool must become a multi team internal application. Open endpoints are not acceptable for company use.

## Decision

Use Microsoft Entra ID (Azure AD) JWT bearer authentication with app roles mapped to `admin`, `reviewer`, and `read_only`.

Local development may set `AUTH_DISABLED=true` to bypass Entra. This flag must never be enabled in production.

## Consequences

- Requires Entra app registration and role assignment per team member
- Browser UI will integrate MSAL.js in a later slice
- API keys for automation remain a separate slice (015)
