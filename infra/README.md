# Infrastructure: BASK'D on Cloud Run

Terraform for running BASK'D on Google Cloud Run in the team's `baskd-calendar` project.
One configuration serves two environments with separate state and separate resources:

| Environment | What it is | Service name | State prefix |
| --- | --- | --- | --- |
| `prod` | The service we demonstrate and submit | `baskd` | `baskd/prod` |
| `staging` | Disposable, for release and rollback drills | `baskd-staging` | `baskd/staging` |

## What it creates

| Resource | What it is for | What breaks without it |
| --- | --- | --- |
| `google_project_service.apis` | Enables Cloud Run, Artifact Registry, Secret Manager, IAM, Cloud Trace, Logging and Monitoring | Nothing else can be created |
| `google_artifact_registry_repository.images` | Holds release images, pulled by digest | Cloud Run has no image to run |
| `google_service_account.runtime` | The identity the container runs as; it can read one secret and nothing else | The service would run as the default compute account, which can edit the whole project |
| `google_secret_manager_secret.calendar_key` | Holds the Calendar service-account key, mounted as a file at runtime | The app fails at startup: `settings.py` requires a key |
| `google_secret_manager_secret.workflow` | One secret per HW3 credential (`<service>-dropbox-app-key`, `-dropbox-app-secret`, `-dropbox-refresh-token`, `-trello-api-key`, `-trello-token`), created empty whichever implementation is chosen (`terraform output workflow_secrets`) | Switching `workflow_storage` / `workflow_issues` to a real implementation has nowhere to read credentials from |
| `google_secret_manager_secret_iam_member.runtime_reads_workflow` | Lets the runtime identity read those secrets (`roles/secretmanager.secretAccessor`, per secret) | The revision fails at startup: Cloud Run cannot inject the variables |
| `google_cloud_run_v2_service.api` | The API, private by default, scaling 0 to `max_instances` | Nothing to call |
| `google_project_iam_member.runtime_writes_traces` | Lets the runtime identity write spans to Cloud Trace (`roles/cloudtrace.agent`, write-only) | Requests still work, but no traces: a slow or failed request can't be split into our work and the Google call |
| `google_logging_metric.requests`, `.request_latency` (`observability.tf`) | Turn the app's per-request log line into traffic, error and latency metrics, by operation | The dashboard has no traffic, error or latency panels |
| `google_monitoring_dashboard.service` (`observability.tf`) | The Level 3 dashboard (`terraform output dashboard_url`) | Someone has to rebuild the charts by hand in the console |
| `google_monitoring_slo.get_availability`, `.get_latency` (`slo.tf`) | The two SLOs for `GET /events/{id}` and their error budgets (`terraform output slo_url`, `docs/SLO.md`) | No promise to measure against, and nothing for the alert to burn |
| `google_monitoring_alert_policy.get_availability_fast_burn` (`slo.tf`) | Emails `alert_emails` when the availability budget burns at 14.4x | Nobody hears about a failing service until a user complains |
| `google_cloud_run_v2_service_iam_member.invokers` | Lets `invokers` call the service; we use `domain:nyu.edu` so course staff can (`docs/DEPLOYMENT.md` §4). Public principals are rejected | Only project owners can call it |
| `google_iam_workload_identity_pool_provider.github` (`deploy.tf`) | Lets this repository's `v*` tags (prod) or `staging-*` tags (staging) sign in from GitHub Actions without a stored key | The deploy workflow cannot reach Google |
| `google_service_account.deploy` (`deploy.tf`) | The identity releases deploy as: push images, roll out revisions, move traffic, call the service for the smoke check. It cannot read the key or change IAM | Releases would need a long-lived key in GitHub, or a person running `gcloud` |

The key itself is **not** in Terraform: Terraform creates an empty secret, and step 2 adds the
key with `gcloud`. So the key never appears in the Terraform state, the repository or CI output.

## Before you start

- [Terraform](https://developer.hashicorp.com/terraform/install) 1.6 or newer, the
  [gcloud CLI](https://cloud.google.com/sdk/docs/install), and Docker **running** (step 3
  builds an image).
- **Billing enabled** on the `baskd-calendar` project. Cloud Run and Artifact Registry refuse
  to start without it.
- Owner on the `baskd-calendar` project (ask the project owner listed in
  `docs/HUMAN_STEPS.md` §0), or at least: Cloud Run Admin, Artifact Registry Admin, Secret Manager
  Admin, Service Account Admin, Service Usage Admin, and Storage Admin on the state bucket.
- Your copy of the Calendar service-account key and the calendar id (`docs/HUMAN_STEPS.md`
  §1–2). The calendar id is the value of `BASKD_GOOGLE_CALENDAR_ID` in your `.env`.
- Log in once, for both gcloud and Terraform. The last line stops gcloud warning that your
  application-default credentials bill a different project:

  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project baskd-calendar
  gcloud auth application-default set-quota-project baskd-calendar
  ```

## Step 0 (once per team): the state bucket

Terraform state is shared through a versioned bucket. Create it once. If it already exists,
skip this step.

```bash
gcloud storage buckets create gs://baskd-calendar-tfstate --location=us-east1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://baskd-calendar-tfstate --versioning
```

## Step 1: preview, then create the repository, identity and secret

```bash
cd infra
cp terraform.tfvars.example prod.tfvars          # calendar_id = BASKD_GOOGLE_CALENDAR_ID from .env
terraform init -backend-config="bucket=baskd-calendar-tfstate" -backend-config="prefix=baskd/prod"
terraform plan -var-file=prod.tfvars -out=tfplan  # read what it will do
terraform apply tfplan
```

With no `image` set yet, this creates everything except the Cloud Run service.

## Step 2: put the Calendar key in Secret Manager

Point `--data-file` at your copy of the key. In a fresh clone `secrets/` is empty, so use
wherever you keep it:

```bash
gcloud secrets versions add "$(terraform output -raw calendar_key_secret)" \
  --data-file=/path/to/your/service-account.json
gcloud secrets versions list "$(terraform output -raw calendar_key_secret)"
```

**Do not go on until the list shows one enabled version.** If step 3 runs first, the new
revision fails with `secret …/versions/latest was not found` and leaves a failed service
behind (the next apply replaces it).

### Step 2b (HW3): the Dropbox and Trello credentials

Only needed before you set `workflow_storage` to `team3` / `team1` or `workflow_issues` to
`team4`; the defaults (`memory`) read no secrets. Get the values first
(`docs/HUMAN_STEPS.md` §8), export them in your shell, then add one version per secret.
The script reads the variables and pipes each one to `gcloud`, so no value lands in your
shell history or on disk; unset variables are skipped:

```bash
export DROPBOX_APP_KEY=... DROPBOX_APP_SECRET=... DROPBOX_REFRESH_TOKEN=...
export TRELLO_API_KEY=... TRELLO_TOKEN=...
../scripts/add_workflow_secrets.sh prod       # or: staging
for s in $(terraform output -json workflow_secrets | jq -r '.[]'); do
  gcloud secrets versions list "$s" --limit=1
done
```

**Same rule as step 2:** an implementation whose secrets have no version makes the revision
fail at startup. `TRELLO_LIST_ID` is not secret; it goes in `.tfvars` as `trello_list_id`.

## Step 3: push an image and deploy it by digest

Build from a clean checkout of the commit you want to run (normally a release tag):

```bash
REPO=$(terraform output -raw image_repository)
SHA=$(git rev-parse --short HEAD)
gcloud auth configure-docker us-east1-docker.pkg.dev
docker build --platform linux/amd64 -t "$REPO/baskd:$SHA" ..
docker push "$REPO/baskd:$SHA"
gcloud artifacts docker images describe "$REPO/baskd:$SHA" --format='value(image_summary.digest)'
```

Put the digest in `prod.tfvars`. The image must be pinned by digest; `terraform plan` rejects
a tag such as `:latest`.

```hcl
image = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:<digest>"
```

Then preview and apply again:

```bash
terraform plan -var-file=prod.tfvars -out=tfplan
terraform apply tfplan
```

## Step 4: call the API

The service is private: callers send a Google identity token. Project owners can call it, and
so can anyone in `invokers`. We set `invokers = ["domain:nyu.edu"]` so teammates and course
staff can call it with their NYU account (`docs/DEPLOYMENT.md` §4); `allUsers` is rejected.

```bash
URL=$(terraform output -raw service_url)
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" "$URL/health"
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title": "Infra check", "start": "2030-01-07T15:00:00Z", "end": "2030-01-07T15:30:00Z"}' \
  "$URL/events"
# Delete what you created, using the id from the response:
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$URL/events/<id>"
```

The HW3 workflow (`docs/DESIGN.md`, "HW3"). `/health` says which storage and issue tracker
are live:

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title": "Infra check", "start": "2030-01-07T15:00:00Z", "end": "2030-01-07T15:30:00Z",
       "agenda": "1. Check the deploy"}' \
  "$URL/workflows/meeting-prep"
```

## Step 5: check that a repeated apply changes nothing

```bash
terraform plan -var-file=prod.tfvars
```

It should end with `No changes. Your infrastructure matches the configuration.`

## Releases after the first one

Step 3 only seeds the first revision. After that, releases go through
`.github/workflows/deploy.yml` (`docs/DEPLOYMENT.md` §5): push a `v*` tag for prod or a
`staging-*` tag for staging. Terraform ignores which image is running and how traffic is
split, so `terraform plan` stays clean after a release. Keep `image` in your `.tfvars` as it
is; it is only used when the service is first created.

After a release, traffic is pinned to that release's revision. So a later `terraform apply`
that changes the service's configuration (an environment variable, scaling, the timeout)
creates a new revision that gets **no traffic**. The change goes live with the next release,
or move traffic to the new revision by hand:
`gcloud run services update-traffic baskd --region us-east1 --to-latest`.

### Switching the HW3 implementations

The implementation swap and the failure demo are both configuration changes, made the same
way. Set the variables in the environment's `.tfvars`:

```hcl
workflow_storage = "team1"    # team3 | team1 | memory | failing
workflow_issues  = "team4"    # team4 | memory | failing
trello_list_id   = "<24 hex characters>"   # required with team4
```

Then apply, move traffic to the new revision (see the previous paragraph) and confirm:

```bash
terraform plan -var-file=prod.tfvars -out=tfplan && terraform apply tfplan
gcloud run services update-traffic baskd --region us-east1 --to-latest
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"
```

`failing` makes every call to that vertical fail with a provider error, so the workflow's
partial-failure response can be shown on the deployed service. Set it back afterwards.

**The Milestone 1 evidence (#68)** is three runs, one configuration change apart. With the
Dropbox and Trello variables still exported from step 2b, `scripts/hw3_evidence.py` also
confirms the file and the card in Dropbox and Trello themselves:

| Run | `workflow_storage` | `workflow_issues` | Command |
| --- | --- | --- | --- |
| Composed workflow | `team3` | `team4` | `python ../scripts/hw3_evidence.py "$URL" compose --out evidence.md` |
| Swap one vertical | `team1` | `team4` | `python ../scripts/hw3_evidence.py "$URL" swap --out evidence.md` |
| Controlled failure | `team1` | `failing` | `python ../scripts/hw3_evidence.py "$URL" failure --out evidence.md` |

Export `BASKD_SMOKE_TOKEN=$(gcloud auth print-identity-token)` first. Each run exits non-zero
if the service did not behave as documented. Paste `evidence.md` into #68, and keep the
records: graders look them up in the providers.

The workflow's provider and identity are fixed names derived from the environment, and match
these outputs:

```bash
terraform output workload_identity_provider deploy_service_account
```

## The staging environment

Same steps with its own state prefix and variables file. `terraform init -reconfigure`
switches the backend, so prod's state is never touched from a staging session.

```bash
cp terraform.tfvars.example staging.tfvars       # set environment = "staging"
terraform init -reconfigure -backend-config="bucket=baskd-calendar-tfstate" \
  -backend-config="prefix=baskd/staging"
terraform plan -var-file=staging.tfvars -out=tfplan && terraform apply tfplan
```

## Teardown

For each environment you created, re-init with its prefix and destroy:

```bash
terraform init -reconfigure -backend-config="bucket=baskd-calendar-tfstate" -backend-config="prefix=baskd/prod"
terraform destroy -var-file=prod.tfvars
```

This removes the Cloud Run service, the image repository and its images, the secret and its
versions, the runtime and deploy service accounts, and the GitHub workload identity pool.

Google keeps a deleted workload identity pool for 30 days and its id cannot be reused in that
time. So a `destroy` followed by an `apply` within 30 days fails on `baskd-github` (or
`baskd-staging-github`). Restore the pool instead of recreating it, then apply again:
`gcloud iam workload-identity-pools undelete baskd-github --location=global`.

Left behind on purpose:

- **The enabled APIs.** Other things in the project use them (`disable_on_destroy = false`).
- **The state bucket.** Delete it last, after every environment is destroyed:
  `gcloud storage rm --recursive gs://baskd-calendar-tfstate`.
- **The Calendar service account, its key and the calendar's sharing.** They were set up by
  hand (`docs/HUMAN_STEPS.md` §1–2) and are used by local development and CI too. Remove them
  at the end of the course as that document describes.

## Offline checks

`terraform test` plans the configuration against a mocked Google provider. It needs no
credentials and creates nothing:

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test
```

## Questions from the first provisioning run

A teammate who did not write this provisions it from this page and records here every question
they had to ask, and the README is updated to answer it.

First run: Arda Dinc, Nov 11, 2026, prod and staging ([review on #49](https://github.com/samthropic/BASKD/pull/49)).

| Question | Answer (now in this page) |
| --- | --- |
| Step 3 ran before the key was in, and Cloud Run failed with `secret …/versions/latest was not found`. How do I know step 2 worked? | Step 2 ends with `gcloud secrets versions list`; don't go on until it shows one version |
| Why does Cloud Run (or Artifact Registry) refuse to start, and why does step 3 fail to build? | "Before you start" now lists billing on the project and Docker running |
| gcloud warns that the application-default credentials' quota project doesn't match. Does that matter? | The login block now ends with `gcloud auth application-default set-quota-project baskd-calendar` |
| `--data-file=../secrets/service-account.json` fails in a fresh clone. Where is the key? | Step 2 says to point at your own copy; `secrets/` is empty in a fresh clone |
| What is `calendar_id`? | `BASKD_GOOGLE_CALENDAR_ID` from `.env`, named in "Before you start", step 1 and `terraform.tfvars.example` |
