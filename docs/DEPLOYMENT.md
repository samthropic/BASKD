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

## 4. A managed platform (example: Google Cloud Run)

Cloud Run is a natural fit (we already have a Google Cloud project, it scales to zero, and
the free tier covers a course project). Sketch, to be turned into a tested script when the
team decides to deploy:

```bash
PROJECT=baskd-calendar REGION=us-east1
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# 1. Store the key in Secret Manager (never in an env var in the console UI)
gcloud secrets create baskd-service-account --data-file=secrets/service-account.json

# 2. Build and deploy from source (Cloud Build uses our Dockerfile)
gcloud run deploy baskd --source . --region "$REGION" \
  --set-env-vars BASKD_PROVIDER=google,BASKD_GOOGLE_CALENDAR_ID="<calendar id>" \
  --set-secrets  /run/secrets/baskd/service-account.json=baskd-service-account:latest \
  --set-env-vars BASKD_GOOGLE_CREDENTIALS_FILE=/run/secrets/baskd/service-account.json \
  --no-allow-unauthenticated       # keep it private until the API has its own auth
```

Notes: Cloud Run injects `PORT`, which the image honours. With `--no-allow-unauthenticated`
callers need an identity token (`gcloud auth print-identity-token`), which doubles as our
missing caller authentication for now. Alternatives with similar effort: Fly.io, Render,
Railway; all accept a Dockerfile and secrets as env vars (use `BASKD_GOOGLE_CREDENTIALS_JSON`
there).

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
