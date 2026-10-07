# Requirements, assumptions and acceptance criteria

The handout is intentionally vague. This document is where we turn it into something
testable: what we believe Levels 1 and 2 require for the **calendar** category, the
assumptions we made where the handout leaves a choice open, the questions we still owe staff,
and how we know each requirement is met.

Status legend: ✅ implemented and tested · 🟡 implemented, needs confirmation · ⬜ not started

## 0. What the team has actually been given

The complete definition of Milestone 1 available to us is:

> **First working version** (due October 7, 2026)
> - A polished GitHub repository where you talk to your selected vertical's provider and
>   tests to verify.
> - This includes Level 1 and Level 2 of Specs.

plus the general handout sections (learning goals, §1.1 scope, §2 teamwork). **No document
available to the team defines what "Level 1" and "Level 2" contain.** Rather than wait, we
wrote down in §1 what a reasonable Level 1/2 for the calendar vertical must mean, built it,
and asked staff to confirm (§4, question 1). If the Levels turn out to include something
else, the gap becomes an issue and the table below is corrected; nothing is silently dropped.

Acceptance criteria that follow directly from the three phrases of the milestone text:

| Phrase | What we take it to mean | Where it is met |
| --- | --- | --- |
| "polished GitHub repository" | A newcomer can clone, install, run and test from the README alone; CI is green; issues/PRs follow templates; workflow and decisions are written down; no secrets or junk committed | README quick start, `uv.lock`, `.github/` (templates, CI, release draft), `AGENTS.md`, `docs/`, `.gitignore`/`.dockerignore` |
| "talk to your selected vertical's provider" | The service performs real create/read/list/update/delete operations against a real Google Calendar through the official API, not a stub | `baskd/providers/google.py`; `make demo` against Google; `tests/integration/` |
| "tests to verify" | Automated tests for expected behaviour and edge cases at every layer, plus tests that exercise the real provider and clean up after themselves | `tests/unit/` (130 tests), `tests/integration/` (4 tests, self-skipping without credentials), CI |

## 1. What we believe Levels 1 and 2 ask for (assumption, see §0)

### Level 1: a thin slice through the whole system (first working version)

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1.1 | A FastAPI service that runs locally from a documented, reproducible setup | ✅ | README quick start; `uv.lock`; CI `checks` job |
| 1.2 | Real provider integration: create an event through our API and see it in the provider's calendar | ✅ against Google by `tests/integration`; 🟡 until the team runs it with real credentials | `tests/integration/test_google_calendar.py::test_create_get_list_replace_delete`; `scripts/demo.py` |
| 1.3 | Retrieve the event through our API and compare it with what was created | ✅ | same test (`fetched.json() == event`) |
| 1.4 | Public behaviour independent of the provider: the same API works on a fake | ✅ | `baskd/ports.py`; identical API tests pass on `InMemoryCalendarProvider` |
| 1.5 | Dependency injection of the concrete provider | ✅ | `create_app(settings, provider)`; `api/dependencies.py` |
| 1.6 | Test doubles for repeatable testing | ✅ | `providers/memory.py`, `tests/conftest.py::FailingProvider` |
| 1.7 | Health/liveness endpoint | ✅ | `GET /health` |

### Level 2: expand behaviour, handle real integration problems

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 2.1 | **Invalid input** rejected with clear, consistent errors | ✅ | 422 envelope with `details`; `tests/unit/test_api_events.py::TestCreate::test_invalid_input_is_422_with_details` |
| 2.2 | **Collections of results**: list events in a time window, ordered, paginated | ✅ | `GET /events?from&to&limit&cursor`; overlap semantics tests in `test_memory_provider.py::TestList`; real pagination in `tests/integration::test_pagination_cursor_round_trip` |
| 2.3 | Update an event | ✅ | `PUT /events/{id}` (full replacement) |
| 2.4 | Delete an event; subsequent reads 404 | ✅ | `TestDelete` unit + integration |
| 2.5 | **Provider failures** surfaced honestly (timeouts, auth, quota, 5xx) rather than as 500s | ✅ | `providers/google.py::translate_http_error`; `tests/unit/test_api_errors.py` |
| 2.6 | Provider limitations identified early and reflected in the API | ✅ | README "Provider limitations"; §3 below |
| 2.7 | **Repeated requests** (idempotent create / retries) | ⬜ assumed Level 3 | `docs/NEXT_STEPS.md` |
| 2.8 | Recurring or all-day event creation, attendees, multiple calendars | ⬜ assumed out of scope for M1 | `docs/NEXT_STEPS.md` |

If the real Level 2 text includes 2.7 or 2.8, they move up; the design already has a home
for each (see NEXT_STEPS).

## 2. Assumptions and decisions (each one is a choice the handout left open)

| Decision | Alternatives considered | Why this one | Consequence |
| --- | --- | --- | --- |
| **Provider: Google Calendar via a service account** | Microsoft Graph (needs Azure AD app + admin consent), CalDAV (less "real"), Google with user OAuth (browser consent flow, refresh tokens to store) | Zero-interaction auth: a key file + sharing a calendar with the robot. Free, well-documented SDK. Any teammate can set it up in 15 minutes | Service accounts cannot invite attendees without domain-wide delegation; see §3 |
| **One calendar per service instance** (configured, not in the URL) | `/calendars/{id}/events` | Matches "use a test calendar containing data your team may change"; prevents a caller from reaching any other calendar the robot can see | Multi-calendar support = a settings change + path parameter later |
| **Inputs must be tz-aware; outputs are UTC** | Echo the caller's offset; accept naive as UTC | Google returns times in the *calendar's* zone, the fake would return the caller's; UTC is the only answer both can give identically. Naive timestamps are a classic bug source | Clients convert for display. Sub-second precision is dropped (Google stores whole seconds) |
| **Strict input: unknown fields and query params → 422** | Ignore unknown keys | A typo (`?form=`) silently returning the wrong window is worse than a 422 | Clients must send exactly the documented fields |
| **List = overlap with `[from, to)`** | "Starts within window" | Identical to Google's `timeMin`/`timeMax`, so the fake and the real provider agree without translation | Documented in README and the model docstring |
| **`PUT` full replacement, no `PATCH` yet** | `PATCH` with merge | Full replacement has no merge edge cases (e.g. moving only `start` past the old `end`) and reuses the create validation unchanged | Clients re-send all fields; `PATCH` is in NEXT_STEPS |
| **Second `DELETE` → 404** | 204 (idempotent) | Honest about provider behaviour (Google: 410 Gone) and simplest for the fake to mirror | Documented in the API table |
| **No retries inside the service for M1** | SDK `num_retries` | Retrying a `POST` without an idempotency key can create duplicates; we return 503 + `Retry-After` and let the caller decide | "Repeated requests / provider failures" level adds retries with idempotency |
| **One error envelope** `{"error": {code, message, details?}}` | FastAPI's default `{"detail": ...}` | Stable machine-readable `code` is testable and does not leak provider messages except where useful (`invalid_request`) | Custom handlers in `api/errors.py` |
| **Synchronous handlers** | `async` + async Google client | The official SDK is sync; FastAPI runs sync handlers in a thread pool; simpler to reason about | Per-call `AuthorizedHttp` for thread safety |
| **`uv` + lockfile, Python 3.12 only** | pip + requirements.txt, Poetry | Exact reproduction with one command; fast CI | Everyone installs `uv` |
| **Default provider = `memory`** | Fail without config | `uv run uvicorn ...` works on a fresh clone; `/health` and the startup log always state the provider in use | A teammate must set `BASKD_PROVIDER=google` deliberately |

## 3. Provider limitations identified (and how the API reflects them)

| Google Calendar fact | Reflected as |
| --- | --- |
| Service accounts cannot invite attendees without domain-wide delegation (Google returns 403 `forbiddenForServiceAccounts`) | No attendee field in the API |
| Deleted events: `events.get` may return `status: "cancelled"`; `events.delete` on a deleted event → 410 Gone | Both → `404 event_not_found` |
| 404 is returned both for a missing event and for a calendar the robot cannot see | 404 on get/replace/delete → `404 event_not_found`; 404 on create/list → `502 provider_auth_error` with a "not shared" hint |
| All-day events have `date` not `dateTime` | Read as `all_day: true` with midnight-UTC bounds; cannot be created or replaced (`PUT` → `400 invalid_request`, event unchanged) |
| Recurring events are one resource with instances | Listed as expanded instances (`singleEvents=true`), cannot be created; `PUT` on a series → `400 invalid_request`, on a single occurrence → replaces only that occurrence |
| `events.update` replaces the whole resource; sending back the fetched resource is Google's documented way to preserve fields we do not manage | `PUT` is fetch-modify-update inside the provider |
| Times come back in the calendar's time zone | Normalised to UTC |
| `googleapiclient`'s HTTP transport is not thread-safe | Fresh `AuthorizedHttp` + explicit timeout per call |
| Quota errors arrive as 403 with `rateLimitExceeded`/`userRateLimitExceeded` as well as 429 | All → `503 provider_unavailable` + `Retry-After` |
| Google rejects `end <= start` ("The specified time range is empty") | Caught by our validation first (422); if it ever reaches Google → `400 invalid_request` |

## 4. Open questions for staff (post in `#help`)

1. The Milestone 1 description says it "includes Level 1 and Level 2 of Specs", but no
   material we have defines the Levels. Where are they published, or can you share them? Our
   working assumption for the calendar vertical is: Level 1 = create and read an event through
   our API against the real provider; Level 2 = list (collections, time window, pagination),
   update, delete, input validation and honest provider-error handling. Is idempotency
   ("repeated requests") Level 2 or later?
2. Is a service account (robot identity, no end-user OAuth) an acceptable "real provider
   integration", given it cannot invite attendees?
3. Is one configured calendar per deployment acceptable, or must the API address multiple
   calendars?
4. We are considering an extension where the service also reads and drafts replies to email
   (Gmail). Does that count as part of the calendar category / extra credit, or would it be
   judged as scope creep? (Our own view: not before Levels 3+ are solid; see NEXT_STEPS.)
5. Is the "review release" the Milestone 2 deliverable, or is Milestone 1 already expected to
   have a prerelease tag?

## 5. Acceptance walkthrough (what "done" looks like for Milestone 1)

Run by a teammate who did not write the code, from a fresh clone, on the tagged commit:

1. `uv sync --locked && make check` → all green.
2. `make run` with `.env` pointing at the shared test calendar → startup log says
   `provider=google`.
3. `make demo` → prints `All steps behaved as documented.`; open the `web_link` printed after
   "create event" in a browser and see the event in Google Calendar before the script deletes it
   (add a `sleep` or run the steps manually if you want to watch).
4. `uv run pytest -m integration -ra` → the 4 integration tests pass; the test calendar has no
   leftover `baskd-integration …` events afterwards.
5. Post the terminal output on the milestone issue.
