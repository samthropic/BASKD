# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/) (see AGENTS.md §5 for the scheme).
Release notes on GitHub are built from the matching section here.

## [Unreleased]

### Added (Level 5: consistent failure handling)
- Error table in the README: for every error code, when it occurs, its HTTP status, which
  kind of failure it is (invalid input, missing resource, access denied, provider failure,
  bug) and whether the caller may retry.
- `X-Request-ID` on every response (the caller's own id if well-formed, otherwise a new one).
- One structured JSON `request_failed` log line per failed request: operation, error code
  and category, HTTP status, whether the provider was called, retryability and request id.
  No bodies, query strings, event ids, credentials or provider text are logged; only bugs
  (`internal_error`) log a stack trace.
- Integration test for a real provider failure: a calendar not shared with the service
  account is reported as `502 provider_auth_error`.

### Changed
- Error messages no longer include Google's error text (it can echo request data); they
  are the service's own provider-neutral sentences. Codes and statuses are unchanged.

### Fixed (Team 6 review of `v0.1.0-rc.1`)
- Time zones declared by Google now resolve on machines without a system time-zone database
  (Windows): `tzdata` is a declared dependency. Before, such zones silently became UTC.
  An unknown zone name still reads as UTC but now logs a warning.
- Numbers and numeric strings (Unix time) are rejected as timestamps with `422` instead of
  being read as 1970 dates, in event bodies and in `from`/`to`.
- `from`/`to` are truncated to whole seconds, so the in-memory and Google providers agree at
  the window boundary.
- A list cursor is only accepted with the `from`/`to` it was issued for; another window
  returns `400 invalid_request` instead of silently continuing a different listing.
  Cursors are re-encoded by the API, so cursors issued by earlier versions are invalid.

### Added
- Get Event HTTP contract tests shared by the in-memory and Google adapters (fake SDK),
  including injection, app isolation, UTC output, optional fields and failure translation.
- Explicit Get Event read guarantees in the provider port, README and OpenAPI, including
  the existing `422 validation_error` response for an overlong id (no API behaviour change).
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

### Changed
- `PUT /events/{id}` on an all-day event or a recurring series now returns
  `400 invalid_request` and leaves the event unchanged. Previously Google silently turned an
  all-day event into a timed one, and a series failed with Google's own "Missing time zone
  definition" error. Single occurrences of a recurring event can still be replaced.

### Known limitations
- No caller authentication: run on `127.0.0.1` only.
- Attendees, creating all-day or recurring events, multiple calendars, `PATCH`, idempotent
  create and automatic retries are not implemented (see docs/NEXT_STEPS.md).
- The Google provider has been verified against the real API only once team credentials are
  configured (docs/HUMAN_STEPS.md); until then it is covered by offline tests with recorded
  response shapes.
