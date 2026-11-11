# Deployment

The handout only requires a runnable **source release** (clone the tag, follow the README).
This document covers the other ways to run the service, in increasing order of effort, so the
team can choose deliberately. Nothing here is required for Milestone 1.

> Before exposing the service anywhere other than `127.0.0.1`, read the security note in the
> README: the API has no caller authentication yet. Whoever can reach the port can edit the
> calendar.

## 1. Configuration contract (same everywhere)

The service is configured only through environment variables (or a `.env` file in the working
directory). See the README table. Two of them are secrets:

- `BASKD_GOOGLE_CREDENTIALS_FILE` (path) **or** `BASKD_GOOGLE_CREDENTIALS_JSON` (inline). Use
  the file form when the platform can mount a secret as a file, the inline form when it can
  only inject environment variables.
- `BASKD_GOOGLE_CALENDAR_ID` is not secret but is environment-specific.

Health checks:

- `GET /health` (liveness) returns 200 and names the active provider. It does not call
  Google, so it is safe for aggressive probing, and Cloud Run's startup and liveness probes
  use it: a Google outage cannot make the platform restart healthy instances in a loop.
- `GET /ready` (readiness) makes one cheap Google call and returns 503 with the error code
  as `reason` while requests would fail (Google down, key revoked, calendar not shared).
  Use it to ask "would a request work right now?"; nothing restarts the service on it.

The process is stateless when `BASKD_PROVIDER=google` (all state lives in the calendar), so
it can be restarted, scaled horizontally, or replaced at will. With `memory` it holds state in
RAM and is only for development.

## 2. Local (source release)

```bash
git clone https://github.com/samthropic/BASKD.git && cd BASKD
git checkout v0.1.0            # the release tag being verified
uv sync --locked
cp .env.example .env           # fill in; key file under secrets/
uv run uvicorn baskd.app:create_app --factory --host 127.0.0.1 --port 8000
```

Production-ish flags: drop `--reload`, add `--workers 2` if you want more than one process
(safe: no shared in-process state with the Google provider), and put a reverse proxy with TLS
in front if the host is reachable from elsewhere.

## 3. Docker

The image is built from `Dockerfile` (multi-stage, locked dependencies, non-root user,
`$PORT`-aware, built-in `HEALTHCHECK`). CI builds it on every push and checks `/health`.
The builder stage installs `git`, because the shared `calendar-contract` package is a git
dependency. The build therefore needs network access to github.com.

```bash
docker build -t baskd:dev .

# in-memory, no credentials
docker run --rm -p 8000:8000 -e BASKD_PROVIDER=memory baskd:dev

# real provider: mount the key read-only, point the service at it
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e BASKD_GOOGLE_CREDENTIALS_FILE=/run/secrets/baskd/service-account.json \
  -v "$PWD/secrets:/run/secrets/baskd:ro" \
  baskd:dev
```

The key never enters the image: `.dockerignore` excludes `secrets/` and `.env*`, and the
runtime stage only copies the virtualenv. Verify with `docker history baskd:dev` if in doubt.

## 4. Google Cloud Run (the deployed service)

The deployed service runs on Cloud Run in the `baskd-calendar` project, provisioned with
Terraform. [`infra/README.md`](../infra/README.md) is the procedure: the state bucket, putting
the key in Secret Manager, pushing an image and deploying it by digest, calling the API with
an identity token, and teardown. It has two environments, `prod` (the one we demonstrate) and
`staging` (disposable, for release drills), with separate state and resources.

Why Cloud Run: our project, the Calendar service account and the test calendar already live in
Google Cloud, it scales to zero, and the key can be mounted from Secret Manager as a file.
The service stays private (`invokers` in Terraform) because the API has no caller
authentication of its own; callers send `gcloud auth print-identity-token`. Fly.io, Render and
Railway would also run the image, with the key in their secret store as
`BASKD_GOOGLE_CREDENTIALS_JSON`.

## 5. Promoting a release

Releases go out through [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml). Nobody
runs `gcloud run deploy` by hand.

1. The release coordinator pushes an annotated `v*` tag on a commit whose CI is green
   (`AGENTS.md` §5). A `staging-*` tag runs the same pipeline against `baskd-staging`.
2. The workflow signs in to Google with Workload Identity Federation as the environment's
   **deploy** identity (`infra/deploy.tf`). No key is stored in GitHub. The identity accepts
   only this repository's tags with that environment's prefix, so a drill tag can never deploy
   to prod.
3. It builds the image **once** from the tagged commit and `uv.lock`, pushes it to Artifact
   Registry, and deploys it **by digest** (`@sha256:…`) as a candidate revision with **no
   traffic**, under a temporary `rc-<sha>` tag URL.
4. `scripts/smoke.py` runs health, create, get, replace and delete against the candidate on
   the real calendar, and deletes what it made.
5. Only if that passes does traffic move to the candidate. The smoke check then runs again
   against the live URL.
6. The GitHub deployment for the environment (repository → Environments) is marked
   successful only when every step passed. The run summary shows the commit, the digest, and
   the revisions before and after.

Configuration does not come from the image. Environment variables, the mounted Calendar key,
scaling and the runtime identity come from Terraform and Secret Manager. Terraform ignores the
running image and traffic split (`lifecycle` in `infra/main.tf`), so a release does not make
the next `terraform plan` want to change anything.

## 6. Rollback and what it does not undo

**Automatic.** If the smoke check fails, or anything fails after the candidate was deployed,
the workflow sends 100% of traffic back to the revision that was serving before the run,
reruns the smoke check against it, and fails the run. A candidate that fails its smoke check
never receives traffic.

**By hand** (a problem found after a release passed):

```bash
gcloud run revisions list --service baskd --region us-east1     # newest first
gcloud run services update-traffic baskd --region us-east1 --to-revisions <previous>=100
BASKD_SMOKE_TOKEN=$(gcloud auth print-identity-token) python scripts/smoke.py "$(gcloud run services describe baskd --region us-east1 --format='value(status.url)')"
```

Old revisions keep their image digest and configuration, so this is a traffic switch, not a
rebuild. Then fix forward with a new tag. If the release notes listed a **setup or
configuration change** (new env var, new secret, new calendar), roll that back in Terraform as
well.

What rolling back cannot undo: events created, modified or deleted in the calendar by the
defective version, including a write that timed out and may have been stored anyway. The
Google Calendar UI's trash holds deleted events for about 30 days and can restore them by hand;
our service has no bulk restore. A defective release issue (see `AGENTS.md` §5) must state
which events, if any, were affected.

### Rollback drill (recorded)

Run in the disposable `baskd-staging` service:

1. [`staging-drill-good`](https://github.com/samthropic/BASKD/actions/runs/43082678541): a good
   release. Candidate `baskd-staging-00002-fem` passed its smoke check, took 100% of traffic,
   and passed again on the live URL. A `terraform plan` afterwards showed no changes.
2. [`staging-drill-broken`](https://github.com/samthropic/BASKD/actions/runs/43083004869): a
   deliberately broken release (a tag-only commit where replace raises, so it answers 500).
   Candidate `baskd-staging-00005-taj` failed its smoke check at `replace` (`HTTP 500`), so it
   never received traffic. The rollback step pinned 100% of traffic to the previous revision,
   `baskd-staging-00002-fem`, the smoke check passed against it, and the run failed, so the
   release was not marked successful.

The smoke check deletes its own events even when it fails, so the drill leaves nothing in the
calendar.
