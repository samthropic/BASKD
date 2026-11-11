# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/) (see AGENTS.md §5 for the scheme).
Release notes on GitHub are built from the matching section here.

## [Unreleased]

### Breaking changes
- Error codes renamed to the names Teams 2, 5 and 7 share in their joint Calendar API
  contract: `validation_error` and `invalid_request` → `invalid_input` (still `422` and
  `400`), `event_not_found` → `not_found`, `provider_auth_error` → `access_denied`. HTTP
  statuses are unchanged. Clients that branch on `code` must update, and tell the two
  `invalid_input` cases apart by status. (#31)

## [0.1.0] - 2026-10-21

Final release (spec Level 5 plus review feedback). Tag `v0.1.0`.

### Added (Level 5: consistent failure handling) — #18, #20
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

### Added (tests, demo and write-ups) — #21, #22, #24, delete demo
- Boundary tests extending create (`POST /events`) and listing (`GET /events`): title,
  description and location exactly at and one past their limits, `limit` 250 and 251, and
  a window holding exactly `limit` events (one page, `next_cursor` null). No behaviour change.
- `TUTORIAL.md`: the demo against Google Calendar, expected vs actual per step with terminal
  screenshots, one section per operation owner (listing with `limit=1` paging and a cursor
  refused for another window; delete with a second delete reported as `404`; more sections
  as their owners add them).
- `TESTING.md` (testing strategy and known gaps), `docs/COST.md` (cost of `GET /events`),
  `docs/DECISIONS.md` (service account bound to one calendar), and
  `docs/FINAL_RELEASE_CHECKLIST.md`.
- Release process: the coordinator publishes only after the fresh-checkout verification is
  linked, and the verifier states their OS (`AGENTS.md` §5, reasons in
  `docs/TEAM_AGREEMENT.md` §7).

### Changed
- Error messages no longer include Google's error text (it can echo request data); they
  are the service's own provider-neutral sentences. Codes and statuses are unchanged.
- The package version reported by `GET /health` and OpenAPI is now `0.1.0`. It had been
  left at `0.1.0a1` in `v0.1.0-rc.1`.

### Fixed (Team 6 review of `v0.1.0-rc.1`) — #17, #19
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

### Known limitations
- No caller authentication: run on `127.0.0.1` only.
- Attendees, creating all-day or recurring events, multiple calendars, `PATCH`, idempotent
  create and automatic retries are not implemented (see `docs/NEXT_STEPS.md`).
- No idempotency keys or automatic retries: a `POST` that timed out may have succeeded, so
  list the window before re-sending.
- Testing gaps are listed in `TESTING.md` ("Known gaps").

## [0.1.0-rc.1] - 2026-10-14

Review prerelease (spec Levels 3–4). Tag `v0.1.0-rc.1`, commit `1628bab`.

### Added
- Get Event HTTP contract tests shared by the in-memory and Google adapters (fake SDK),
  including injection, app isolation, UTC output, optional fields and failure translation (#15).
- Explicit Get Event read guarantees in the provider port, README and OpenAPI, including
  the existing `422 validation_error` response for an overlong id (no API behaviour change).
- `docs/REVIEW_RELEASE_CHECKLIST.md` with the Levels 3–4 evidence and task owners (#16).

### Known at release
- The package version was still reported as `0.1.0a1`.

## [0.1.0-alpha.1] - 2026-10-07

First working version (spec Levels 1–2, Milestone 1). Tag `v0.1.0-alpha.1`, commit `57b7a7d`.

### Added
- FastAPI calendar service with a pluggable provider: `GET /health`, `POST /events`,
  `GET /events/{id}`, `GET /events?from&to&limit&cursor`, `PUT /events/{id}`,
  `DELETE /events/{id}`.
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
  DEPLOYMENT, NEXT_STEPS, TEAM_AGREEMENT; per-operation ownership and real-provider
  verification by every member (#2, #11, #12, #13).

### Changed
- `PUT /events/{id}` on an all-day event or a recurring series returns
  `400 invalid_request` and leaves the event unchanged (#14). Previously Google silently
  turned an all-day event into a timed one, and a series failed with Google's own "Missing
  time zone definition" error. Single occurrences of a recurring event can still be replaced.

[Unreleased]: https://github.com/samthropic/BASKD/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/samthropic/BASKD/compare/v0.1.0-rc.1...v0.1.0
[0.1.0-rc.1]: https://github.com/samthropic/BASKD/compare/v0.1.0-alpha.1...v0.1.0-rc.1
[0.1.0-alpha.1]: https://github.com/samthropic/BASKD/releases/tag/v0.1.0-alpha.1
