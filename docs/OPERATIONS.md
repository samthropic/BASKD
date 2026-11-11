# Operations guide

How to run BASK'D in production without reading the source or CI config. Owner: Sam (#46).
Provisioning and teardown live in [`infra/README.md`](../infra/README.md); release and
rollback live in [`DEPLOYMENT.md`](DEPLOYMENT.md). Telemetry walkthroughs are in
[`OBSERVABILITY.md`](OBSERVABILITY.md); SLOs, the burn-rate alert and the error budget policy
are in [`SLO.md`](SLO.md).

Environments: **prod** service `baskd`, **staging** service `baskd-staging`, both in project
`baskd-calendar`, region `us-east1`.

## 1. Five questions (≈ 10 minutes)

| Question | Where to look | What you should see |
| --- | --- | --- |
| What is running? | Cloud Run → Services → `baskd` (or `gcloud run services describe baskd --region us-east1`) | One service, private (invokers only), scaling 0–`max_instances` (default 2) |
| Which version? | Cloud Run → Revisions (the one with 100% traffic), or the image digest on that revision; after #44, the dashboard "Deployed release" panel / `jsonPayload.release` on a log line (`0.2.0+abc1234`) | A single digest serving 100%. Candidate `rc-*` tags are not traffic |
| Is it healthy? | Liveness: `GET /health` with an identity token (`infra/README.md` step 4). Both Cloud Run probes also hit `/health` (there is no separate readiness probe). Calendar actually usable right now: `GET /ready` (#52) | `/health` → `200` and `"provider": "google"` (never calls Google, so it stays green in an outage). `/ready` → `200` when the provider can serve; `503` with `reason` set to our error `code` when it cannot |
| Where are the logs? | Logs Explorer: `resource.type="cloud_run_revision" resource.labels.service_name="baskd"` | Today: one `request_failed` JSON line per failed request (`baskd.api.failures`). After #44: one line per request (`request_succeeded` / `request_failed`) with `release` and `trace_id` |
| How do I roll it back? | [`DEPLOYMENT.md`](DEPLOYMENT.md) §6 | Automatic if smoke fails. By hand: point 100% traffic at the previous revision, then re-run `scripts/smoke.py`. Calendar side effects are **not** undone |

Staging answers the same questions with service name `baskd-staging`. Prefer staging for
drills; prod is the submission service.

## 2. Runbook: likely failures

For each case: how it shows up, what to do, and what recovery cannot undo. Error codes match
the README error table.

| Failure | What you see | Mitigation | Cannot undo |
| --- | --- | --- | --- |
| Google outage / 5xx / timeout | Clients get `503 provider_unavailable` (reads/deletes) or `502 provider_error` (create/replace whose outcome is unknown). Logs: `category` `provider_failure`, often near `BASKD_GOOGLE_TIMEOUT_SECONDS` (10 s). After #44: Google child span slow or missing an answer | Wait / retry reads and deletes after `Retry-After`. For a timed-out **write**, **do not** re-POST/PUT blindly: `GET` the id or list the window first. Check [Google Calendar status](https://www.google.com/appsstatus) | A create/replace that timed out may already exist in the calendar |
| Expired or revoked Calendar service-account key | Startup failure, or every Google call becomes `access_denied`. Logs: auth / refresh failures; no successful provider calls | Project owner rotates the key (`HUMAN_STEPS.md` §1) and adds a new Secret Manager version (`infra/README.md` step 2). Running instances keep the old key until they restart; after a release, traffic is pinned, so a bare `gcloud run services update` revision gets **no** traffic. Rotation is: add the version, deploy a new revision, then move traffic to it (or cut a release). Then revoke the old key | Nothing in the calendar; the service was just unable to talk to it |
| Calendar no longer shared with the robot | `access_denied` ("calendar not found or not shared"). Provider was called | Calendar owner re-shares "BASK'D test calendar" with the service-account email, **Make changes to events** (`HUMAN_STEPS.md` §2) | Same as above |
| Quota / rate limit exhausted | `503 provider_unavailable` (Google 429 / quota reasons). Burst of failures under load | Lower traffic, raise backoff on the client, or temporarily lower `max_instances` / concurrency. Quota is Google's, not Cloud Run's | A 429 means the write was **not** applied; safe to retry after waiting |
| Bad release reaches traffic | Errors spike only on the new `release` label / revision; smoke may have passed a narrow path | Roll traffic back ([`DEPLOYMENT.md`](DEPLOYMENT.md) §6). Open `Release vX.Y.Z: <problem>` within the hour (`AGENTS.md` §5). Fix forward with a new tag | Events the bad revision created, changed or deleted. Calendar trash keeps deletes ~30 days; we have no bulk restore |
| Deploy / smoke failure (candidate never promoted) | Deploy workflow red; automatic rollback already ran | Read the Actions summary (digest, previous revision). Fix the tag's commit; do not force traffic to a failed candidate | Smoke deletes its own events even on failure, so a failed promote leaves the calendar clean |

Caller mistakes (`invalid_input`, `not_found`) are not operator incidents: fix the request.

## 3. Three Terraform resources that matter most

Full table: [`infra/README.md`](../infra/README.md). These three are the ones an on-call should
be able to name:

| Resource | What it is for | What breaks without it |
| --- | --- | --- |
| `google_cloud_run_v2_service.api` | The API itself (private, probes on `/health`) | Nothing to call |
| `google_secret_manager_secret.calendar_key` | Holds the Calendar key (mounted as a file; key bytes added with `gcloud`, not Terraform) | App refuses to start (`settings.py` requires a key) |
| `google_service_account.deploy` (+ WIF provider in `deploy.tf`) | Identity GitHub Actions uses to push images, roll revisions, move traffic, and smoke-check | Releases need a long-lived key in GitHub, or a human running `gcloud` |

Related: the **runtime** service account can read that one secret and nothing else; it is
not the Calendar robot (that robot's key is *inside* the secret).

## 4. Cost, owner, teardown

| Item | Estimate / note |
| --- | --- |
| Expected monthly cost | Near **$0–a few USD** at demo traffic. Calendar API: no charge. Cloud Run scales to 0; default 512Mi / 1 vCPU, `max_instances=2`. Artifact Registry and Secret Manager stay in free tiers at our volume. After #44: log-based metrics and the dashboard are free at this volume; Cloud Logging free allotment 50 GiB/month (~0.5 KB per request line); Cloud Trace free tier 2.5M spans/month. Main avoidable Cloud Run cost after telemetry: `cpu_idle = false` keeps an instance billed until Cloud Run stops it (~15 minutes after the last request) |
| GCP project owner | **Arda Dinc**, project `baskd-calendar` (`HUMAN_STEPS.md` §0) |
| Teardown date | **2026-12-15** (after Milestone 3 is graded). Procedure: `infra/README.md` "Teardown" for each environment, then delete the state bucket. Also remove the Calendar service account, its keys and the test-calendar sharing (`HUMAN_STEPS.md`) |

Raise unexpected bills on the course `#help` channel early.

## 5. Blast radius

| Identity / event | What it can do | What it cannot do |
| --- | --- | --- |
| **Deploy** identity (`baskd-deploy` / `baskd-staging-deploy`) | Push images to that environment's Artifact Registry repo; create revisions and move traffic on that environment's Cloud Run service; `actAs` the runtime SA; invoke the service for smoke. It cannot read the Calendar key directly, but a leaked deploy credential could still reach it **indirectly** by pushing an image and deploying it as the runtime identity (which can read the secret) | Change IAM; touch the other environment. WIF accepts only this repository's id and that environment's tag prefix (`v*` vs `staging-*`) |
| **Runtime** identity | Read the one Secret Manager secret mounted into the container | Edit the project, push images, or call Google Calendar as itself (Calendar access is the **key inside** the secret) |
| **Leaked CI / GitHub token** | With only `contents` + `id-token` as in `deploy.yml`, an attacker still needs a tag push on **this** repo that matches the WIF condition. Forks do not get a token for this repository | There is **no** long-lived Google key in GitHub secrets for deploy. A leaked Calendar key file (from a laptop / `secrets/`) can edit every calendar shared with that robot |
| **One bad merge to `main`** | Breaks the next release tag's build or runtime behaviour. Does **not** auto-deploy: only a `v*` / `staging-*` tag runs `deploy.yml` | Cannot by itself rewrite prod traffic. Worst case after someone tags it: a bad revision that passes smoke, then mutates the shared test calendar until rolled back |

## 6. Signals → actions

The dashboard and request logs are defined in `infra/observability.tf` and described in
[`OBSERVABILITY.md`](OBSERVABILITY.md); open the board with `terraform output dashboard_url`.
The symptom alert is in `infra/slo.tf`, described in [`SLO.md`](SLO.md#the-alert).

| Signal | What it means | What to do differently |
| --- | --- | --- |
| Traffic by operation | Who is calling what | No traffic during a demo: check Cloud Run / invoker tokens. Spike: check saturation |
| Errors by operation and category | Whose fault | `invalid_input` / `not_found`: caller. `provider_failure`: Google path (runbook above). `access_denied`: key or sharing. `internal`: bug — grab `X-Request-ID` / stack |
| Latency p95 (successes) | Slow happy path | Compare app time vs Google span (after #44); if Google dominates, it is not our code |
| Latency p95 (failures) | Fast reject vs hang | Failures near 10 s → Google timeout |
| Saturation (concurrent req / instance vs limit 20) | Instances full | Near 20 with `max_instances` running: raise `concurrency` or `max_instances` in Terraform. That apply creates a new revision with **no** traffic until the next release or `gcloud run services update-traffic … --to-latest` (`infra/README.md`) |
| Requests by release | Which digest is live | Errors that start with a new release → roll back ([`DEPLOYMENT.md`](DEPLOYMENT.md) §6) |
| Burn-rate / SLO alert ([`SLO.md`](SLO.md#the-alert)) | Error budget for `GET /events/{id}` is burning fast | Open the dashboard, confirm category, follow the matching runbook row; pause risky deploys per the [error budget policy](SLO.md#error-budget-policy) |

### From a red panel to one request (after #44)

1. Note operation, category and minute on the errors panel.
2. Open the log query from the dashboard text panel; filter e.g. `jsonPayload.request_id="…"`.
3. Follow the log line's trace link; the Google child span is the provider call.

## Related links

- Infra setup / teardown: [`infra/README.md`](../infra/README.md)
- Deploy + rollback drill: [`DEPLOYMENT.md`](DEPLOYMENT.md)
- Credentials and calendar sharing: [`HUMAN_STEPS.md`](HUMAN_STEPS.md)
- Telemetry detail: [`OBSERVABILITY.md`](OBSERVABILITY.md) (#44)
- SLOs, alert and error budget policy: [`SLO.md`](SLO.md)
- Release process: [`AGENTS.md`](../AGENTS.md) §5
