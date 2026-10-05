# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/) (see AGENTS.md §5 for the scheme).
Release notes on GitHub are built from the matching section here.

## [Unreleased]

### Added
- Milestone 1 ("first working version", Levels 1-2): FastAPI calendar service with a
  pluggable provider.
- Endpoints: `GET /health`, `POST /events`, `GET /events/{id}`,
  `GET /events?from&to&limit&cursor`, `PUT /events/{id}`, `DELETE /events/{id}`.
- Google Calendar provider (service account, one configured calendar) and an in-memory
  provider for development and tests.
- Strict input validation (tz-aware timestamps, `end > start`, unknown fields rejected) and
  one error envelope `{"error": {"code", "message", "details?"}}` with stable codes.
- Provider failure translation: timeouts/5xx/quota → `503 provider_unavailable`
  (+ `Retry-After`), credential/permission problems → `502 provider_auth_error`,
  deleted events → `404 event_not_found`.
- Test suite: unit tests (models, fake provider, HTTP behaviour, error envelope, Google
  mapping and error translation with a fake SDK, settings) and auto-skipping integration tests
  against the real calendar.
- CI (lint, format, strict typing, tests with coverage, Docker build + health check,
  conditional integration run), draft-release workflow on `v*` tags, Dockerfile.
- Documentation: README, AGENTS.md (workflow, review, release), docs/REQUIREMENTS.md
  (assumptions, acceptance criteria, open questions), ARCHITECTURE, HUMAN_STEPS,
  DEPLOYMENT, NEXT_STEPS, TEAM_AGREEMENT (draft).

### Known limitations
- No caller authentication: run on `127.0.0.1` only.
- Attendees, creating all-day or recurring events, multiple calendars, `PATCH`, idempotent
  create and automatic retries are not implemented (see docs/NEXT_STEPS.md).
- The Google provider has been verified against the real API only once team credentials are
  configured (docs/HUMAN_STEPS.md); until then it is covered by offline tests with recorded
  response shapes.
