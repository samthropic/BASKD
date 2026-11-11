# Observability (HW2 M3 Level 3)

How to tell what BASK'D is doing from its telemetry alone: the dashboard, the request log and
the traces. Owner: Bryant (#44). Code: `src/baskd/api/request_log.py`, `src/baskd/telemetry.py`,
`providers/google.py::_google_call_span`. Infrastructure: `infra/observability.tf`.

## Where to look

| What | Where |
| --- | --- |
| Dashboard | `terraform output dashboard_url` in `infra/` (one per environment: "BASK'D (prod)", "BASK'D (staging)"). Staging: <https://console.cloud.google.com/monitoring/dashboards/builder/d9f31f44-9d08-45f0-8739-5a2ce867e001?project=baskd-calendar> |
| Request log | Logs Explorer, query `resource.type="cloud_run_revision" resource.labels.service_name="baskd" jsonPayload.event=("request_succeeded" OR "request_failed")` (`baskd-staging` for staging). The dashboard's text panel links to it. |
| Traces | Trace Explorer for `baskd-calendar`, or the trace link on a log entry |
| Which release is running | The dashboard's "Deployed release" panel, or `jsonPayload.release` on any log line (`0.2.0+1a2b3c4` = version + commit) |

## The request log line

Every request except `/health` writes one JSON line. Cloud Logging stores it as `jsonPayload`:

| Field | Meaning |
| --- | --- |
| `event`, `outcome` | `request_succeeded`/`success` or `request_failed`/`failure` |
| `operation` | Route name: `create_event`, `get_event`, `list_events`, `replace_event`, `delete_event`; `unknown` for an unknown path |
| `status`, `error`, `category`, `retryable` | HTTP status, our error code and category (failures only) |
| `provider_involved` | Whether Google was called. `false` on a 422 means we rejected the request ourselves |
| `latency_ms` | Server-side time from the request reaching the app to the response |
| `release` | Version + commit of the running image |
| `request_id` | The `X-Request-ID` the caller got back. Ask a caller for it |
| `trace_id` | The request's trace. The entry's `trace` field holds the same id, which is why Logs Explorer can link to the trace |

Never logged: bodies, titles, query strings, event ids (only the route template), headers,
credentials, Google's error text.

## Dashboard panels

| Panel | Question it answers | What an operator does after seeing it |
| --- | --- | --- |
| Traffic: requests per minute, by operation | Is anyone using it, and which operations? | No traffic during a demo: the service or the caller is down; check Cloud Run. A spike: check the saturation panel |
| Errors per minute, by operation and category | What is failing, and whose fault is it? | `invalid_input`/`not_found`: caller problem, nothing to fix. `provider_failure`: Google is slow or down; check traces for the Google span. `access_denied`: the Calendar key or sharing broke; check the secret. `internal`: our bug; read the `stack_trace` in the log line |
| Latency p95, successful requests | Is it slow for callers? | Compare with the Google span in a slow request's trace: if the Google call takes most of the time, it's Google; otherwise it's our code |
| Latency p95, failed requests | Do failures fail fast or hang? | Failures near 10 s are Google timeouts (`BASKD_GOOGLE_TIMEOUT_SECONDS`) |
| Saturation: concurrent requests per instance vs. limit of 20 | Are instances full? | Near 20 with `max_instances` (2) running: raise `concurrency` or `max_instances` in `infra/variables.tf` |
| Deployed release: requests by release | Which release is serving, and did a rollout or rollback happen? | After a release, only the new release should have traffic. Errors that start with a new release: roll back (docs/DEPLOYMENT.md §6) |

Latency is split by outcome because a fast 422 and a 10-second Google timeout would otherwise
average into a misleading number. Saturation is per service, not per operation: all
operations share the same instances and the same concurrency limit.

## From the dashboard to one request

1. In the errors panel, note the operation and category, and the minute.
2. Open the request log (link in the dashboard's text panel) and add a filter, for example
   `jsonPayload.category="provider_failure"`, or `jsonPayload.request_id="<id>"` if a caller
   reported one.
3. On the entry, open the trace (Logs Explorer shows a trace link because of the entry's
   `trace` field), or paste `trace_id` into Trace Explorer.
4. In the trace, the server span is named after the route (`GET /events/{event_id}`). Its
   child `google calendar.events.<method>` span is the call to Google, with Google's HTTP
   status. Time outside that child span is our own work (validation, conversion, logging).

## Recorded walkthrough on staging (2026-11-11, release `0.1.0+f393a14`)

Deployed with tag `staging-telemetry-1` (deploy run 43093116401: smoke checks passed before and
after the traffic move). Requests sent with `X-Request-ID` set so they are easy to find:

| Case | Request | Response | Log line (`jsonPayload`) | Trace |
| --- | --- | --- | --- | --- |
| Success | `POST /events` | 201 | `request_succeeded`, `create_event`, 201, `latency_ms` 865.2, `INFO` | `c825277add16c5af1336d243c57e1670` |
| Invalid request | `POST /events` with `end` before `start` | 422 `invalid_input` | `request_failed`, `create_event`, `invalid_input`, `provider_involved: false`, 1.7 ms, `WARNING` | `656479dd7f4755524f12a19241002378` |
| Provider failure | `GET /events?limit=1` on a revision with `BASKD_GOOGLE_TIMEOUT_SECONDS=0.001`, reached through a `fault` tag with no traffic | 503 `provider_unavailable`, `Retry-After: 5` | `request_failed`, `list_events`, `provider_failure`, `retryable: true`, 150.2 ms, `ERROR`; the Google adapter's line before it says `Google Calendar unreachable: TimeoutError` | `0680ed18df1c352b746e7a8fb485f1bf` |

The `<name>_requests` metric counted all of them (and the smoke checks) with labels
`operation`, `outcome`, `category`, `status` and `release` only. Afterwards the `fault` tag
was removed and the timeout set back to 10; traffic never left the normal revision.

**Not yet shown:** the traces themselves. The runtime identity's `roles/cloudtrace.agent`
grant needs a project Owner (an Editor gets 403 on project IAM), so on this run the app logged
`Error while writing to Cloud Trace` and no spans arrived. The span structure is covered by
`tests/unit/test_google_provider.py::test_trace_shows_the_google_call_as_a_child_span`. Once
the grant is applied, rerun the three requests and add their trace screenshots here.

A teammate who didn't write this (rubric §15.3) still has to do the walkthrough above from the
dashboard alone and say where they needed help.

## Safety and limits

- Metric labels hold only bounded values (operation, outcome, category, status, release).
  `infra/tests/plan.tftest.hcl` fails if an id or path becomes a label.
- Spans carry the route template, method, status and our error code. Exception recording is off
  because exception text can contain event ids. FastAPI's built-in telemetry is off because it
  records `url.path` and `url.query`.
- Every request is traced (at most 3 spans per request). Cloud Trace's free tier is 2.5M spans a
  month; switch to a ratio sampler in `telemetry.py` if traffic gets near that.
- `latency_ms` is measured inside the app. It cannot see time spent in Cloud Run's front end, a
  cold start before the app is up, or requests Cloud Run rejected before they reached the app
  (for example a missing identity token, which is a 403 from Cloud Run itself).
- `/health` is not logged or traced, so probes don't show up as traffic.
- Cost: log-based metrics and the dashboard are free at this volume. Cloud Logging's free
  allotment is 50 GiB a month, and one request line is about 0.5 KB. `cpu_idle = false` keeps an
  instance billed until Cloud Run stops it, about 15 minutes after the last request. Owner:
  Bryant. Teardown: with the rest of the stack (`infra/README.md`).
