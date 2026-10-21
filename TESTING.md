# Testing strategy

What our tests establish about BASK'D, why we picked those cases, how to run them, and what
they do **not** establish. The spec's testing section asks for exactly this; the API
contract itself is in the [README](README.md#the-api).

## Running the tests

| Command | What runs | Needs |
| --- | --- | --- |
| `make check` | ruff, ruff format, mypy strict, then `pytest` | nothing |
| `uv run pytest -m "not integration"` | the fast suite only (~225 tests, ~2 s) | nothing: no network, no credentials |
| `make test-integration` (`uv run pytest -m integration -ra`) | the real-Google suite (6 tests, ~20 s) | `.env` with `BASKD_PROVIDER=google` and credentials ([`docs/HUMAN_STEPS.md`](docs/HUMAN_STEPS.md)) |
| `make cov` | fast suite with a line and branch coverage report | nothing |

Without credentials, the integration tests skip themselves with a reason. A plain `pytest`
runs them when `.env` is configured, so expect ~20 s more. CI ([`ci.yml`](.github/workflows/ci.yml))
runs the fast suite and the Docker health check on every push and pull request, and the real-Google
suite on pull requests in this repository (it needs repository secrets).

Coverage on the fast suite is 98% of lines and branches. That is a way to find untested
code, not evidence: the tables below say which behaviours the tests establish.

## Where each kind of test lives

| Boundary (spec 1.2) | File | Doubles | What it can and cannot show |
| --- | --- | --- | --- |
| Validation rules | [`test_models.py`](tests/unit/test_models.py) | none | Every accept/reject rule, without HTTP |
| HTTP behaviour | [`test_api_events.py`](tests/unit/test_api_events.py) | `InMemoryCalendarProvider` | Status codes, bodies, headers, workflows through FastAPI |
| Error contract and failure logs | [`test_api_errors.py`](tests/unit/test_api_errors.py), [`test_failure_logging.py`](tests/unit/test_failure_logging.py) | `FailingProvider` (raises a chosen error on every call) | Every error class through every route, and the log line it leaves |
| One operation across both adapters | [`test_get_contract.py`](tests/unit/test_get_contract.py) | memory provider, and the Google adapter on a fake SDK | That `GET /events/{id}` means the same thing whichever provider is injected |
| Google adapter | [`test_google_provider.py`](tests/unit/test_google_provider.py) | `FakeEvents`, a fake `service.events()` that records requests and returns canned resources or raises `HttpError` | Request shaping, resource mapping, error translation. **Only as good as our assumptions about Google**, see below |
| Fake provider | [`test_memory_provider.py`](tests/unit/test_memory_provider.py) | none | That the fake honours the port's contract, so HTTP tests on it mean something |
| Configuration and wiring | [`test_settings_and_app.py`](tests/unit/test_settings_and_app.py) | a throwaway RSA key | Settings validation, credential loading, provider selection, injection |
| The real provider | [`tests/integration/test_google_calendar.py`](tests/integration/test_google_calendar.py) | none | Authentication, SDK behaviour, pagination and error translation against Google itself |

Assumptions the Google fakes encode, each checked by an integration test against the real
API: a deleted event reads as 404 (`test_create_get_list_replace_delete`); a calendar the
service account cannot see answers 404, which we report as an access denial
(`test_calendar_the_service_cannot_see_is_an_access_denial`); `nextPageToken` pages through
a window (`test_pagination_cursor_round_trip`); all-day events and recurring series come back
as described in [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) §3
(`test_replace_refuses_all_day_and_series_but_moves_one_occurrence`). Assumptions **not**
checked live: Google's quota/5xx/timeout responses, and Google ignoring fractional seconds in
`timeMin`/`timeMax` (taken from Google's documentation).

## Behaviours, the cases we chose, and where they are tested

### Input validation (create and replace bodies, list query)

*Contract:* timestamps are ISO 8601 strings with an offset; `end > start`; title 1–1024
characters, non-blank; description ≤ 8192 and location ≤ 1024 characters; unknown fields are
rejected; `limit` is 1–250. A rejected request writes nothing.

*Partitions and boundaries:* naive vs offset-bearing timestamps; numbers and numeric
strings, which pydantic would otherwise read as Unix time (a Team 6 finding); `end == start`
and `end < start`; blank, whitespace-only and over-long titles; text one character past
each length limit; `limit` 0, 1 and 251; empty cursor; a misspelled query parameter.

*Tests:* `test_models.py::TestEventInput`, `TestListEventsQuery`;
`test_api_events.py::TestCreate::test_invalid_input_is_422_with_details`,
`test_numeric_timestamps_are_422_and_nothing_is_created`,
`TestList::test_invalid_query_is_422`,
`TestReplace::test_invalid_body_is_422_and_event_is_unchanged`. Rejection before any provider
call is shown by `test_get_contract.py::test_invalid_id_is_rejected_before_provider_call` and by
`provider_involved: false` in `test_failure_logging.py::test_invalid_input_never_reaches_the_provider`.

### Create and read (workflow)

*Contract:* `POST` returns 201, a `Location` header and the event with a new id and UTC
times; `GET` on that id returns the same event; any offset in is UTC out; repeating a `POST`
creates a second event (not idempotent, by design).

*Tests:* `TestCreate::test_returns_201_with_location_and_utc_times`,
`test_created_event_is_retrievable`, `test_repeating_request_creates_distinct_events`,
`TestReplace::test_accepts_any_offset_and_returns_utc`, all of `test_get_contract.py`, and
end to end against Google in `test_create_get_list_replace_delete`.

### Listing and traversal (Bryant's operation)

*Contract:* events overlapping the half-open window `[from, to)`, ordered by start, at most
`limit` per page; follow `next_cursor` until `null`; a cursor is only valid with the window
that produced it; bounds are truncated to whole seconds.

*Partitions (spec worked example, n events in the window, page limit L):*

| Case | Test |
| --- | --- |
| n = 0 | `test_api_events.py::TestList::test_empty`, `test_memory_provider.py::TestList::test_empty_calendar` |
| 0 < n < L | `test_window_and_ordering` (2 matching, L = 50) |
| n > L, several pages, every event exactly once, pages ≤ L | `test_traversal_returns_every_event_exactly_once` (7 events, L = 3), `test_pagination_round_trip`, `test_memory_provider.py::test_pagination_walks_every_item_exactly_once` |
| smallest limit, L = 1 | `test_cursor_reused_with_another_window_is_400`, `test_cursor_allows_another_limit_and_another_spelling_of_the_window` |
| event ending exactly at `from` / starting exactly at `to` | `test_memory_provider.py::TestList::test_window_bounds_are_half_open` |
| fractional bound | `test_fractional_upper_bound_is_truncated_like_google`, `test_google_provider.py::test_list_sends_bounds_in_whole_seconds` |
| cursor: absent, valid, malformed (four shapes), wrong window, same window spelled with another offset, changed `limit` | `TestList::test_malformed_cursor_is_400`, `test_cursor_reused_with_another_window_is_400`, `test_cursor_allows_another_limit_and_another_spelling_of_the_window` |
| real provider pagination | `test_pagination_cursor_round_trip` |

Expected results are computed from the fixture (the ids we created, in start order), not by
re-running the traversal code.

### Replace

*Contract:* full replacement: omitted or `null`/`""` optional fields are cleared, the id
never changes; an invalid body is 422 even for an unknown id, and leaves the event unchanged;
all-day events and recurring series are refused with 400 and left unchanged; a single
occurrence can be replaced.

*Tests:* `TestReplace` in `test_api_events.py`;
`test_google_provider.py::test_replace_fetches_then_updates_full_resource`,
`test_replace_unrepresentable_event_is_refused_without_updating` (no `update` call is made),
`test_replace_404_on_update_is_not_found` (deleted between fetch and update); against Google,
`test_replace_refuses_all_day_and_series_but_moves_one_occurrence`.

### Delete and repeat

*Contract:* 204, then 404 for the same id on both `GET` and `DELETE`; other events are
untouched.

*Tests:* `TestDelete::test_delete_is_204_then_404`, `test_delete_does_not_affect_other_events`,
`test_google_provider.py::test_delete_success_and_already_deleted` (Google's 410), and against
Google in `test_create_get_list_replace_delete`.

### Failures and the error contract (Level 5)

*Contract:* the README [error table](README.md#errors): one envelope; codes that separate
invalid input, missing resource, access denial, provider failure and bugs; retry guidance;
`X-Request-ID` on every response; one sanitized `request_failed` log line per failure.

*Cases:* each error class through each of the five routes
(`test_api_errors.py::test_domain_errors_map_to_status_and_code`); spec 5.6's four cases
(success, invalid, missing, provider failure), each checking both the response and the log
line (`test_failure_logging.py`); a bug becomes a generic 500 with a traceback in the log and
nothing internal in the body; request ids echoed or replaced when malformed; no event
content, ids or stack traces in expected-failure logs; Google's error text kept out of
messages and logs (`test_google_provider.py::test_public_messages_are_provider_neutral`,
`test_failed_call_logs_status_and_reasons_but_not_googles_message`); translation of every
Google status and transport failure (`TestTranslateHttpError`,
`test_transport_and_credential_failures`); one real provider failure
(`test_calendar_the_service_cannot_see_is_an_access_denial`).

## Evidence that tests detect defects (spec 1.5, 1.6)

[PR #19](https://github.com/samthropic/BASKD/pull/19) records, for each Team 6 finding, a test
run against the code *before* the fix, with the failing assertion: the time-zone test fails
with exactly the reported symptom (`11:00 UTC != 15:00 UTC`) when `tzdata` is missing; 17
assertions fail on the old `models.py`; the cursor test fails with `200 != 400` on the old
handler. The same PR holds the bug investigation record for the Windows time-zone failure
(expected vs observed, reproduction, cause and evidence, fix and verification).
[PR #20](https://github.com/samthropic/BASKD/pull/20) records the failure-logging tests
failing when the log call, the request-id middleware or the provider-call recording is
removed.

## Known gaps

What the tests do not establish, so nobody claims they do:

- **Uncertain writes.** No test simulates Google accepting a create and the response being
  lost. We have no automatic retries, so the service cannot duplicate an event by itself, but
  a caller retrying a timed-out `POST` can. The README tells callers to list before
  re-sending. Owner if we add retries or idempotency keys: whoever takes that extension.
- **Responsiveness under a slow provider.** Handlers are synchronous and run in FastAPI's
  thread pool, so one slow Google call should not block other requests. No test holds a
  provider call open and shows an unrelated request completing (spec 1.3).
- **Values exactly at a limit.** We test one past each limit (title 1025, description 8193,
  location 1025 characters, `limit` 251) but not the largest accepted value (1024, 8192,
  1024, 250), where an off-by-one in a `<` vs `<=` would show. Owner: whoever next touches
  `models.py`.
- **Exactly n = L.** No listing test has exactly `limit` matching events, the boundary
  where an off-by-one would emit a spurious empty last page. Owner: Bryant.
- **Provider behaviour we only read about.** Quota, 5xx and timeout handling are tested
  only against fakes; the fractional-second behaviour of `timeMin`/`timeMax` comes from
  Google's documentation and was not reproduced live.
- **Platforms.** CI runs Linux; we develop on macOS. Windows is covered only by a test that
  hides the OS time-zone database, which is how Team 6's Windows failure was reproduced.
- **Concurrency.** The in-memory provider uses a lock; nothing tests overlapping writes.
  Google applies its own ordering.
