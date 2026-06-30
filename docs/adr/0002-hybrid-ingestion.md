# ADR 0002: Hybrid ingestion (captions before Video Indexer)

## Status

Accepted (2026-06-05)

## Context

Metadata only audits miss spoken claims and on screen text. Full Video Indexer on every audit is slow and costly on free tier infrastructure.

## Decision

1. Always fetch YouTube metadata via Data API v3.
2. Attempt captions via timedtext, then yt-dlp automatic captions.
3. Fall back to Azure Video Indexer when captions are unavailable and VI env vars are configured.

Store `ingestion_source` on each audit for traceability.

## Consequences

- Faster path for videos with captions
- VI remains optional for richer OCR when needed
- Admin can see which ingestion path was used per audit
