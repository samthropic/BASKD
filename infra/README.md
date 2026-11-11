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
| `google_project_service.apis` | Enables Cloud Run, Artifact Registry, Secret Manager and IAM | Nothing else can be created |
| `google_artifact_registry_repository.images` | Holds release images, pulled by digest | Cloud Run has no image to run |
| `google_service_account.runtime` | The identity the container runs as; it can read one secret and nothing else | The service would run as the default compute account, which can edit the whole project |
| `google_secret_manager_secret.calendar_key` | Holds the Calendar service-account key, mounted as a file at runtime | The app fails at startup: `settings.py` requires a key |
| `google_cloud_run_v2_service.api` | The API, private by default, scaling 0 to `max_instances` | Nothing to call |
| `google_cloud_run_v2_service_iam_member.invokers` | Lets named people call the service | Only project owners can call it |

The key itself is **not** in Terraform: Terraform creates an empty secret, and step 2 adds the
key with `gcloud`. So the key never appears in the Terraform state, the repository or CI output.

## Before you start

- [Terraform](https://developer.hashicorp.com/terraform/install) 1.6 or newer, the
  [gcloud CLI](https://cloud.google.com/sdk/docs/install) and Docker.
- Owner on the `baskd-calendar` project (ask the project owner listed in
  `docs/HUMAN_STEPS.md` §0), or at least: Cloud Run Admin, Artifact Registry Admin, Secret Manager
  Admin, Service Account Admin, Service Usage Admin, and Storage Admin on the state bucket.
- The Calendar service-account key at `secrets/service-account.json` and the calendar id
  (`docs/HUMAN_STEPS.md` §1–2).
- Log in once, for both gcloud and Terraform:

  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project baskd-calendar
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
cp terraform.tfvars.example prod.tfvars          # fill in calendar_id
terraform init -backend-config="bucket=baskd-calendar-tfstate" -backend-config="prefix=baskd/prod"
terraform plan -var-file=prod.tfvars -out=tfplan  # read what it will do
terraform apply tfplan
```

With no `image` set yet, this creates everything except the Cloud Run service.

## Step 2: put the Calendar key in Secret Manager

```bash
gcloud secrets versions add "$(terraform output -raw calendar_key_secret)" \
  --data-file=../secrets/service-account.json
```

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

The service is private: callers send a Google identity token. Project owners can call it; add
anyone else (teammates, the TAs) to `invokers` in `prod.tfvars` and apply.

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

## Step 5: check that a repeated apply changes nothing

```bash
terraform plan -var-file=prod.tfvars
```

It should end with `No changes. Your infrastructure matches the configuration.`

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
versions, and the runtime service account.

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

| Question | Answer (now in this page) |
| --- | --- |
| _(to be filled in by the first run)_ | |
