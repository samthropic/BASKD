# BASK'D

[![CI](https://github.com/samthropic/BASKD/actions/workflows/ci.yml/badge.svg)](https://github.com/samthropic/BASKD/actions/workflows/ci.yml)

Open Source and Professional Software Development, Fall '26 group project.

A small, complete calendar service: a FastAPI HTTP API in front of a **real calendar
provider (Google Calendar)**, with the provider hidden behind one interface so the same API
also runs against an in-memory fake for fast, deterministic tests.

**Status: final release `v0.1.0` (spec Levels 1–5).** Every operation runs against the real
Google Calendar ([`TUTORIAL.md`](TUTORIAL.md) shows each one, expected vs actual), failures
are reported consistently and logged with request ids, and the provider sits behind one
injected interface. [`CHANGELOG.md`](CHANGELOG.md) lists what changed in each release;
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) maps the spec levels to evidence.
Earlier releases: `v0.1.0-alpha.1` (Milestone 1, Oct 7) and `v0.1.0-rc.1` (review release, Oct 14).

## Team

- Sam Fiallos
- Arda Dinc
- Bryant Luna-Ramos
- Karthik Ganeshan
- Daniel Zhang

## Documentation map

| Document | What it answers |
| --- | --- |
| this README | How do I run it, what does the API do, why is it built this way |
| [`TUTORIAL.md`](TUTORIAL.md) | The demo: each operation run against the real calendar by its owner, expected vs actual, with screenshots |
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | What exactly did we commit to for Levels 1-2, under which assumptions, and how do we know it works |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Module-by-module tour, the provider interface, how to add a provider |
| [`TESTING.md`](TESTING.md) | What the tests establish, the cases we chose and why, how to run them, known gaps |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | The engineering decision behind the provider setup: alternatives, evidence, tradeoffs, when to revisit |
| [`docs/COST.md`](docs/COST.md) | The cost of `GET /events`: local work, provider calls, what Google does that we cannot see |
| [`docs/FINAL_RELEASE_CHECKLIST.md`](docs/FINAL_RELEASE_CHECKLIST.md) | What the October 21 final release still needs, with owners and draft release notes |
| [`docs/HUMAN_STEPS.md`](docs/HUMAN_STEPS.md) | Things only a human can do: Google Cloud project, service account key, sharing the test calendar, GitHub secrets, access/permissions |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Running it somewhere other than a laptop (Docker, Cloud Run), configuration and rollback |
| [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) | Prioritised backlog after Milestone 1 (Levels 3+, extensions, process) |
| [`docs/TEAM_AGREEMENT.md`](docs/TEAM_AGREEMENT.md) | How we work together (fill in and accept as a team) |
| [`AGENTS.md`](AGENTS.md) | Development workflow, review and release process; the "what to touch for a given change" map; the instructions coding agents follow in this repo |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | The five-step version of the above for a first contribution |

## Quick start

Requirements: **Python 3.12** (pinned in `.python-version`) and [`uv`](https://docs.astral.sh/uv/)
(`brew install uv`, `pipx install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
`uv` downloads the right Python if you do not have it.

```bash
git clone https://github.com/samthropic/BASKD.git && cd BASKD
uv sync --locked                 # exact dependency versions from uv.lock, into .venv
uv run pytest                    # fast suite; provider tests auto-skip without credentials
BASKD_PROVIDER=memory uv run uvicorn baskd.app:create_app --factory --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive API, or in a second terminal run
`uv run python scripts/demo.py` to watch the create → get → list → replace → delete slice.

To run against the **real Google Calendar**: follow [`docs/HUMAN_STEPS.md`](docs/HUMAN_STEPS.md)
once per team (Google Cloud project, service account, shared test calendar), then

```bash
cp .env.example .env             # set BASKD_GOOGLE_CALENDAR_ID, put the key in secrets/
uv run pytest -m integration     # the same slice against Google; cleans up after itself
uv run uvicorn baskd.app:create_app --factory --reload
```

`make help` lists shortcuts (`make test`, `make lint`, `make typecheck`, `make check`, `make run`,
`make demo`); every target is a one-line `uv` command you can also run directly.

## The API

Interactive docs at `/docs`, OpenAPI JSON at `/openapi.json`. The service is bound to **one**
calendar, chosen by configuration; clients never name a calendar.

| Method & path | Purpose | Success | Errors |
| --- | --- | --- | --- |
| `GET /health` | Liveness; reports which provider is active. Does not call the provider. | `200 {"status":"ok","provider":"google","version":"…"}` | |
| `POST /events` | Create an event | `201` + `Location` header + event | `422` invalid body, `400`, `502`, `503` |
| `GET /events/{id}` | Fetch one event | `200` event | `404`, `422` invalid id, `502`, `503` |
| `GET /events?from=&to=&limit=&cursor=` | List events overlapping a window, oldest first, paginated | `200 {"items":[…],"next_cursor":"…"\|null}` | `422` bad query, `400` bad cursor, `502`, `503` |
| `PUT /events/{id}` | Replace every client-editable field | `200` event | `404`, `422`, `400`, `502`, `503` |
| `DELETE /events/{id}` | Delete | `204` | `404` (also when already deleted), `502`, `503` |

An event looks like:

```json
{
  "id": "k3m9…",                       // provider-assigned, opaque
  "title": "Sprint planning",
  "start": "2026-10-07T15:00:00Z",     // always UTC in responses
  "end":   "2026-10-07T15:30:00Z",
  "all_day": false,                    // read-only; true for all-day events that already exist in the calendar
  "description": null,
  "location": null,
  "web_link": "https://www.google.com/calendar/event?eid=…"   // link into the provider's UI, if any
}
```

`GET /events/{id}` reads without changing the event. Treat the id as opaque (1–1024
characters); a longer id returns `422 validation_error`. A successful read returns the
same provider-neutral event shape above with UTC times and nullable optional fields.
Existing all-day events and individual recurring occurrences can be read. A missing,
deleted or cancelled event returns `404 event_not_found`. Provider authentication failures
return `502`; temporary unavailability returns `503` with `Retry-After: 5`.

To create or replace one, send `title`, `start`, `end` and optionally `description`, `location`.

`POST /events` creates one timed event on the configured calendar. The provider assigns its
opaque `id`; the response uses UTC timestamps and includes a `Location` header for
`GET /events/{id}`. The operation is **not idempotent**: repeating the same request creates
another event. The read-only `all_day` field is always `false` for events created through this
operation, and `web_link` may be `null` when the active provider does not offer a UI link.

```bash
curl -i http://127.0.0.1:8000/events \
  -H 'Content-Type: application/json' \
  -d '{"title":"Sprint planning","start":"2026-10-07T15:00:00Z","end":"2026-10-07T15:30:00Z"}'
```

Rules every client can rely on (each is enforced by a test):

- **Timestamps in must be ISO 8601 strings with an offset** (`…Z` or `…-04:00`); naive
  timestamps and numbers or numeric strings (Unix time such as `0`) are rejected with `422`,
  not guessed. **Timestamps out are UTC.** Sub-second precision is dropped, from event times
  and from the `from`/`to` bounds alike (Google ignores it in list bounds too).
- `end` must be strictly after `start`. `title` must be non-blank (≤ 1024 chars);
  `description` ≤ 8192 chars and `location` ≤ 1024 chars. Unknown fields in the body or query
  string are rejected (`422`), so a typo like `?form=` cannot silently return the wrong data.
- Listing uses **overlap semantics** on the half-open window `[from, to)`: an event is
  included when `event.end > from` and `event.start < to`. Either bound may be omitted.
  `limit` is 1-250 (default 50); `cursor` is opaque and only valid with the same `from`/`to`
  as the request that returned it: another window returns `400 invalid_request` (`limit`
  may change between pages).
- `PUT` is a full replacement: optional fields you omit (or send as `null` or `""`) are
  cleared, and the `id` never changes. The body is validated before the event is looked up,
  so an invalid body is `422` even for an unknown id.
- Every error has one shape, listed under [Errors](#errors) below.
- URL gotcha: a `+` in a query-string timestamp must be percent-encoded (`%2B`), or use `Z`.

### Errors

Every non-2xx response has the body
`{"error": {"code": "<stable_code>", "message": "<human readable>", "details": [...]}}`,
with `details` (per-field `loc`/`msg`/`type`, never your input echoed back) only on
`validation_error`. Branch on `code`; the `message` is for people and may change. Messages
are the service's own: provider error text is never passed through.

| `code` | HTTP | Kind of failure | When | Retry the same request? |
| --- | --- | --- | --- | --- |
| `validation_error` | 422 | invalid input | Body, query or path breaks a rule above (missing field, naive or numeric timestamp, `end <= start`, unknown field, bad `limit`) | No: fix the request |
| `invalid_request` | 400 | invalid input | A malformed cursor, a cursor reused with another `from`/`to`, replacing an all-day event or a recurring series, or a request the provider rejects as invalid | No: fix the request |
| `event_not_found` | 404 | missing resource | get/replace/delete of an id that does not exist or was deleted | No |
| `http_error` | 404 / 405 | missing resource / invalid input | Unknown route (404) or wrong method (405) | No |
| `provider_auth_error` | 502 | access denied | The provider denied *the service* (bad or revoked key, calendar not shared, permission removed). The API has no caller identities, so this is the only denial it reports; an operator must fix it | No |
| `provider_unavailable` | 503 + `Retry-After: 5` | provider failure | Timeout, network error, provider 5xx/429 or exhausted quota | Yes, after `Retry-After`, for reads, `PUT` and `DELETE` (a repeated `DELETE` that already succeeded returns 404). A `POST` that timed out may have created the event: list the window before re-sending, or you may get a duplicate |
| `provider_error` | 502 | provider failure | Any other unexpected provider response | Not blindly: the outcome is unknown, so a retried create may duplicate. Re-read (`GET`/list) first |
| `internal_error` | 500 | bug | An unexpected exception in the service | No: report it with the `X-Request-ID` |

A failed operation is never reported as a success, and a request rejected with 4xx before
reaching the provider (422, cursor 400) has made no change.

**Request ids and failure logs.** Every response carries an `X-Request-ID` header: yours if
you send a well-formed one (`[A-Za-z0-9._:-]`, ≤ 128 chars), otherwise a fresh id. Each
failed request writes one JSON log line on the `baskd.api.failures` logger:

```json
{"event": "request_failed", "operation": "get_event", "status": 404, "error": "event_not_found",
 "category": "not_found", "provider_involved": true, "retryable": false, "method": "GET",
 "route": "/events/{event_id}", "request_id": "6f1c…"}
```

4xx lines are `WARNING`, 5xx lines `ERROR`; only `internal_error` carries a stack trace.
Logs never contain request or response bodies, query strings, event ids (the route
*template* is logged), headers, credentials or provider error text. The Google adapter adds
its own line with the provider's HTTP status and `reason` codes for provider failures.

### Provider limitations reflected in the API

Discovered up front and encoded rather than papered over (details in `docs/REQUIREMENTS.md`):

- **No attendees.** A Google service account cannot invite attendees without domain-wide
  delegation, so the API has no attendee field at all instead of one that silently fails.
- **All-day and recurring events can be read, not created.** Existing all-day events show up
  with `all_day: true` and midnight-UTC bounds; recurring events are listed as individual
  occurrences. `PUT` refuses an all-day event or a whole recurring series with
  `400 invalid_request` and leaves it unchanged (otherwise Google would silently turn an
  all-day event into a timed one); a single occurrence, as returned by `GET /events`, can be
  replaced and only that occurrence changes. Creating either is a documented next step.
- **Deleting is not idempotent at the provider**: Google answers 410 for a second delete and
  may return a "cancelled" event on `GET`. Both are reported as `404 event_not_found`.
- **Google answers 404 both for "no such event" and "no such calendar / not shared".** Only
  the former can be a client error, so a 404 from *create* or *list* is reported as
  `502 provider_auth_error` ("calendar not found or not shared"), while a 404 from
  get/replace/delete is `404 event_not_found`.

## Configuration

All settings are environment variables prefixed `BASKD_`, also read from a `.env` file in the
working directory. `.env.example` documents each one.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BASKD_PROVIDER` | `memory` | `google` for the real provider; `memory` keeps events in process (lost on restart) |
| `BASKD_GOOGLE_CALENDAR_ID` | | Required with `google`. The shared test calendar's id (`…@group.calendar.google.com`) |
| `BASKD_GOOGLE_CREDENTIALS_FILE` | | Path to the service-account key JSON (keep it under `secrets/`, which is git-ignored) |
| `BASKD_GOOGLE_CREDENTIALS_JSON` | | Alternative to the file: the key's JSON inline (used by CI) |
| `BASKD_GOOGLE_TIMEOUT_SECONDS` | `10` | Per-call timeout to Google |
| `BASKD_LOG_LEVEL` | `INFO` | Level for the service's own loggers |

The service fails at startup with a readable message when `google` is selected but the
calendar id or credentials are missing.

> **Security note.** The API itself has **no authentication**: anyone who can reach the port
> can edit the calendar the service is bound to. Milestone 1 runs it on `127.0.0.1` only.
> Adding caller authentication is tracked in `docs/NEXT_STEPS.md`; do not expose the service
> publicly before that lands.

## Design in one picture

```mermaid
flowchart LR
    Client["HTTP client"] -->|JSON| Api["src/baskd/api/<br/>routes · DI · error envelope"]
    Api -->|"EventInput / ListEventsQuery<br/>(validated in models.py)"| Port["ports.py<br/>CalendarProvider protocol"]
    Port -.->|implemented by| Mem["providers/memory.py<br/>fake for tests & dev"]
    Port -.->|implemented by| Goo["providers/google.py<br/>only Google SDK importer"]
    Goo -->|HTTPS| GCal[("Google Calendar")]
    Mem & Goo -->|"Event (UTC) or<br/>baskd/errors.py exception"| Api
    App["app.py · create_app()<br/>settings.py → providers/__init__.py<br/>→ app.state.provider"] --> Api
```

Requests hit thin FastAPI handlers (`baskd/api`) that depend only on the
`CalendarProvider` interface (`baskd/ports.py`). Input is validated once, at the boundary,
by the strict `EventInput`/`ListEventsQuery` models; output is the tolerant, UTC-normalised
`Event` model (`baskd/models.py`). The concrete provider is chosen once in
`create_app()` (`baskd/app.py`) from settings and injected via `app.state` + `Depends`, so tests
pass the in-memory fake (or a failing stub) straight in. Providers translate their SDK's
failures into a small, provider-neutral exception hierarchy (`baskd/errors.py`) that one set of
exception handlers maps to HTTP. `baskd/providers/google.py` is the only module that imports
the Google SDK. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) has the full module map, the
request sequence and the error-translation flow; [`AGENTS.md` §6](AGENTS.md#6-map-for-agents-what-to-touch-for-a-given-change)
has a "what to touch for a given change" table for teammates and their coding agents.

## Development

```bash
make check          # ruff check + ruff format --check + mypy (strict) + pytest, same as CI
make fmt            # auto-format and fix
uv run pytest --cov # coverage report (new code is expected to stay ≥ 90%)
```

CI (`.github/workflows/ci.yml`) runs the checks on every push and pull request, runs the real
Google integration tests when the repository secrets are configured (pushes to `main`,
same-repo PRs, manual dispatch), and builds the Docker image. Pushing a `v*` tag drafts a
GitHub Release for a human to review and publish (`.github/workflows/release.yml`).
The workflow itself, including review and release rules, is written down in
[`AGENTS.md`](AGENTS.md).

## License

See [`LICENSE`](LICENSE).
