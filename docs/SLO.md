# Service level objectives

What BASK'D promises for one representative operation, how we measure it, and what we do when
we break it (HW2 Level 4). Terraform: [`infra/slo.tf`](../infra/slo.tf). The numbers here and
there change together. Owner of this page: the release coordinator of the week.

## The operation: `GET /events/{id}`

It is the read every consumer workflow makes (create, get, replace, delete), it always calls
Google, and it is safe to repeat. So it shows our own failures and Google's without a write
side effect getting in the way.

## The SLIs

Both are measured **at the service**: from the one log line the app writes per request
(`docs/OBSERVABILITY.md`), counted by the Level 3 log-based metrics `<name>_requests` and
`<name>_request_latency`.

### Availability

| | |
| --- | --- |
| Eligible | Every `GET /events/{id}` except `invalid_input` (an id that breaks the rules is the caller's mistake) |
| Good | Eligible and not failed on our side. That includes `200`, and `404 not_found`: a missing event is a correct answer |
| Bad | `provider_failure` (Google down, timing out or rate-limiting us), `access_denied` (key revoked, calendar not shared) and `internal` (a bug) |

`access_denied` counts as bad even though it is not an outage: the caller gets no answer, and
only we can fix it.

### Latency

| | |
| --- | --- |
| Eligible | Every successful `GET /events/{id}` |
| Good | Answered in under **1000 ms**, as measured by the app (`latency_ms`) |

**Where the threshold comes from.** On Nov 11, 2026 we read one event 100 times on staging.
Server-side `latency_ms` for the 97 lines that had reached Cloud Logging: p50 472 ms, p95 555 ms,
p99 561 ms, max 577 ms. Most of a request's time is the call to Google: in the Level 3
walkthrough, a 943 ms create spent 935 ms in the `google calendar.events.insert` span
(`docs/OBSERVABILITY.md`). 1000 ms is about 1.8x the measured p95: room for Google's
variance, and far below the 10 s Google timeout, after which the request fails anyway.

### What the SLIs cannot see

- **Requests that never reach the container.** A Cloud Run outage, a request rejected by Google's
  front end (no identity token, or a caller not in `invokers`), or a cold start that times out
  before our code runs. Those write no log line. Cloud Run's own request metrics would show them,
  but they are not part of this SLI.
- **Time outside our code.** `latency_ms` starts when our middleware gets the request. It misses
  the network, Cloud Run's front end and the container's cold start. A client measured about
  about 0.2 s more at p95 (0.76 s) in the same run.
- **Lost log lines.** If Cloud Logging drops or delays a line, the request is not counted.
  Ingestion took up to a few minutes in our runs.
- **Wrong answers.** A `200` with the wrong event is "good" here. The shared conformance suite
  and the deploy smoke check cover correctness instead.

## The objectives

| SLO | Target | Window | Error budget |
| --- | --- | --- | --- |
| Availability | 99% of eligible gets are good | 28 days, rolling | 1% of eligible gets |
| Latency | 95% of successful gets under 1000 ms | 28 days, rolling | 5% of successful gets |

**Why these targets.**
- **99% availability.** We depend on Google Calendar for every get, so we cannot promise more
  than Google gives us, and the service retries nothing (`docs/ARCHITECTURE.md`). A failed
  read is safe to repeat: when Google is unavailable the response says `retryable: true`. So
  one bad get in a hundred, over four weeks, costs a consumer a retry, not a wrong result.
- **95% under 1000 ms.** In the measured run every get was under 600 ms. 95% rather than 99%
  allows for a slow minute from Google without spending the whole budget on it.
- **28 days.** Long enough that one bad hour doesn't spend the budget, short enough to cover the
  rest of the course.

## Reported values

_Filled in from Cloud Monitoring after each recorded run. Staging values include the alert
drill's deliberate failures, so they are not representative of prod._

| Environment | When | Availability (28 d) | Budget left | Latency (28 d) | Budget left |
| --- | --- | --- | --- | --- | --- |
| staging | 2026-11-11 21:35 UTC, right after the alert drill | 57.7% | **-4,125%** (spent 42x over, by the drill's 120 deliberate failures) | 100% | 100% |
| prod | _(after v0.2.0)_ | | | | |

## The alert

**"BASK'D (prod): GET /events/{id} error budget burning fast"**, in Cloud Monitoring.

- **Symptom-based:** it fires on the error budget burning, not on a cause such as CPU or one
  Google status code.
- **Fires when** the availability budget burns faster than 14.4 times the sustainable rate over
  **both** the last hour and the last 5 minutes. At 14.4x a 28-day budget is gone in under 2 days.
  The 1-hour window keeps a single stray failure from paging. The 5-minute window closes the
  alert within minutes of the failures stopping.
- **Goes to** the `alert_emails` in each environment's `.tfvars`. The message links to the
  dashboard, the runbook row for each error category (`docs/OPERATIONS.md` §2) and the policy
  below.
- **Low traffic.** With few requests, a handful of failures in the same 5 minutes is enough to
  fire. We accept that: at our traffic, a few failed reads in a row is worth a look.
- **Missing data.** With no gets at all there is no burn rate, so the alert stays closed. Silence
  is not a failure here. Noticing that nobody can reach the service (a Cloud Run outage, a broken
  deploy) is the deploy smoke check's job and Cloud Run's own metrics'.

### Tested end to end

Recorded on staging on 2026-11-11, by Karthik Ganeshan (who did not write the telemetry).
Times are UTC.

| Time | What happened |
| --- | --- |
| 21:22:51 | `terraform apply` on staging creates the SLOs, the email channel and the alert (`plan`: 5 to add, 0 to change, 0 to destroy; a second `plan`: no changes) |
| 21:23:30 | A `fault` revision with a 1 ms Google timeout goes up with no traffic (`docs/OBSERVABILITY.md`, "Making a provider failure on purpose") |
| 21:23:54–21:24:04 | 60 `GET /events/{id}` to the fault revision: 60 × `503 provider_unavailable` |
| 21:24:25 | Burn rate: 100x over 5 minutes, 18x over 1 hour (threshold 14.4x) |
| 21:26:47–21:26:58 | 60 more failing gets, to keep the 5-minute window above the threshold |
| **21:27** | **Alert fires.** Two emails from Google Cloud Alerting reach `kg3873@nyu.edu`, one per condition: "Burn rate over 14.4x, last 5 minutes" at 100x and "last 1 hour" at 35.9x. Both carry the dashboard, runbook and policy links |
| 21:28:38–21:28:45 | Fault removed: tag dropped, timeout back to 10 s. Traffic never left the normal revision |
| 21:29:00–21:29:39 | 60 normal gets through the service URL: 60 × `200` |
| 21:32:47 | Burn rate over 5 minutes: 0. The alert's condition is no longer met |
| **~21:34** | **Alert resolves.** Two "Alert recovered" emails, 7 min 3 s after it fired: the 5-minute condition below threshold (6.25x), and the 1-hour condition closed with it (reported as "missing data"). Both conditions must hold for the alert, so it closes as soon as one stops |

From the first failure to the email took about 3.5 minutes, and from the last failure to the
recovery email about 7 minutes. Most of both is the log-based metric's ingestion delay. The drill spent the staging availability budget, as the table above
shows: that is the case the error budget policy below covers.

## Error budget policy

While a budget has some left, we release normally.

When an SLO's 28-day budget is spent:

1. **Stop shipping features to prod.** Only fixes that make the SLO better, and security fixes,
   go out until the budget is positive again.
2. **The release coordinator of the week opens an issue** within a day: what spent the budget
   (from the errors panel and the request log), and the fix.
3. **If one incident spent more than a quarter of a budget**, it gets a short blameless write-up
   in that issue: what happened, how we found out, and what we changed.
4. **If the cause is Google** (a Calendar outage, a quota) and nothing on our side would have
   helped, we record it in the issue and keep shipping. Changing our own code would not bring
   the budget back.

## Where everything lives

| What | Where |
| --- | --- |
| SLOs and error budgets | Cloud Monitoring → Services → `BASK'D API (<env>)`, or `terraform output slo_url` |
| Alert policy | Cloud Monitoring → Alerting, defined in `infra/slo.tf` |
| The metrics both SLIs use | `infra/observability.tf` (Level 3) |
