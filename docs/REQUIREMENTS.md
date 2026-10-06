# Requirements, assumptions and acceptance criteria

The handout is intentionally vague. This document is where we turn it into something
testable: what we believe Levels 1 and 2 require for the **calendar** category, the
assumptions we made where the handout leaves a choice open, the questions we still owe staff,
and how we know each requirement is met.

Status legend: ✅ implemented and tested · 🟡 implemented, needs confirmation · ⬜ not started

## 0. Source of the requirements

The Level definitions are in the **Specs** section of the HW1 handout ("OSPSD Fall '26 - HW1",
linked from the Oct 1 Brightspace announcement). The Oct 3 announcement confirms the scope:

| Milestone | Due | Levels |
| --- | --- | --- |
| First working version | Oct 7, 2026 | Level 1 (one operation, documented and tested) and Level 2 (same operation against the real provider) |
| Review release | Oct 14, 2026 | Level 3 (provider-independent interface) and Level 4 (inject the provider implementation) |
| Final release | Oct 21, 2026 | Level 5 (consistent failure handling) plus review feedback |

Earlier drafts of this file guessed at the Levels before the spec was available. The tables
below are the real Level 1 and Level 2 completion criteria. Some of our code (the `ports.py`
interface, the in-memory provider, dependency injection, the error envelope) goes beyond
Levels 1 and 2; it is ahead of schedule for Levels 3 to 5 and will be revisited against those
levels' text rather than assumed complete.

## 1. Levels 1 and 2: completion criteria

### Operation ownership

The spec requires each member to own one distinct public operation through all five levels,
including its tests and documentation. _Proposed; confirm in the PR review:_

| Operation | Owner | Reviewer |
| --- | --- | --- |
| `POST /events` (create) | _TBD_ | _TBD_ |
| `GET /events/{id}` (read one) | _TBD_ | _TBD_ |
| `GET /events` (list a time window) | _TBD_ | _TBD_ |
| `PUT /events/{id}` (replace) | _TBD_ | _TBD_ |
| `DELETE /events/{id}` (delete) | _TBD_ | _TBD_ |

### Level 1: implement one operation

| # | Completion criterion (spec §1.8) | Status | Evidence |
| --- | --- | --- | --- |
| 1.1 | The service exposes documented public operations (method, route, parameters, success response and status, meaning) | ✅ | README "The API" table; OpenAPI at `/docs` |
| 1.2 | A caller can invoke them and receive the expected response | ✅ | `make run-memory` + `make demo` |
| 1.3 | Each operation's success behaviour is covered by at least one test of public behaviour | ✅ | `tests/unit/test_api_events.py` |
| 1.4 | Documentation matches the implementation | ✅ | README table and tests agree; reviewed in the M1 PR |
| 1.5 | The team can explain what each operation guarantees | 🟡 | Each owner reviews their row of the README table |
| 1.6 | A teammate other than the author reviewed route, request, response, naming, tests and docs | 🟡 | M1 pull request review |

### Level 2: connect to a real provider

| # | Completion criterion (spec §2.9) | Status | Evidence |
| --- | --- | --- | --- |
| 2.1 | The operations use the real provider (Google Calendar) | ✅ in code | `baskd/providers/google.py` |
| 2.2 | The public contract still behaves as documented | ✅ | Same API tests; integration test compares fetched vs created |
| 2.3 | Provider data is translated before it reaches the caller | ✅ | `google.py` maps Google resources to `Event`; no SDK types leave the module |
| 2.4 | Credentials are kept outside the repository | ✅ | `secrets/` and `.env` git-ignored; `.env.example` only |
| 2.5 | Another teammate can follow the docs and run the integration | ⬜ | `docs/HUMAN_STEPS.md`; needs a second member to do it |
| 2.6 | Verified end to end with a real test account (at least two members) | ⬜ | `uv run pytest -m integration -ra` and `make demo` output on the M1 PR |
| 2.7 | At least one integration test or documented manual verification against the real provider | ✅ in code, ⬜ run | `tests/integration/test_google_calendar.py` (skips without credentials) |

**Blocking for Oct 7:** 2.5 and 2.6. They need the Google Cloud service account and the shared
test calendar from `docs/HUMAN_STEPS.md` §1 to §3.

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
| All-day events have `date` not `dateTime` | Read as `all_day: true` with midnight-UTC bounds; cannot be created |
| Recurring events are one resource with instances | Listed as expanded instances (`singleEvents=true`), cannot be created |
| `events.update` replaces the whole resource; sending back the fetched resource is Google's documented way to preserve fields we do not manage | `PUT` is fetch-modify-update inside the provider |
| Times come back in the calendar's time zone | Normalised to UTC |
| `googleapiclient`'s HTTP transport is not thread-safe | Fresh `AuthorizedHttp` + explicit timeout per call |
| Quota errors arrive as 403 with `rateLimitExceeded`/`userRateLimitExceeded` as well as 429 | All → `503 provider_unavailable` + `Retry-After` |
| Google rejects `end <= start` ("The specified time range is empty") | Caught by our validation first (422); if it ever reaches Google → `400 invalid_request` |

## 4. Open questions for staff (post in `#help`)

1. ~~Where are the Levels defined?~~ Answered: the Specs section of the HW1 handout.
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
