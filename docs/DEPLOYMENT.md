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

Health check: `GET /health` returns 200 and names the active provider. It does not call
Google, so it is safe for aggressive probing.

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

1. Only deploy a **tagged** commit whose CI (including the integration job) is green.
2. Deploy with the tag in the image tag / revision name so a rollback is `redeploy previous
   tag`.
3. After deploying: `curl https://<host>/health` → `provider: google`; run
   `python scripts/demo.py https://<host>` (it creates and deletes one event in the test
   calendar).
4. Record the deployment in the GitHub Release ("Deployed to … on …").

## 6. Rollback and what it does not undo

Rolling back means redeploying the previous tag; configuration is versioned with the code, so
nothing else changes unless the release notes listed a **setup or configuration change** (new
env var, new secret, new calendar). Check those first.

What rolling back cannot undo: events created, modified, or deleted in the calendar by the
defective version. The Google Calendar UI's trash holds deleted events for about 30 days and
can restore them manually; there is no API for bulk restore in our service. A defective
release issue (see `AGENTS.md` §5) must state which events, if any, were affected.
