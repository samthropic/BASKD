#!/usr/bin/env bash
# Put the HW3 test accounts' Dropbox and Trello credentials into Secret Manager.
#
#   scripts/add_workflow_secrets.sh prod      # or: staging
#
# Reads the values from your environment (DROPBOX_APP_KEY, DROPBOX_APP_SECRET,
# DROPBOX_REFRESH_TOKEN, TRELLO_API_KEY, TRELLO_TOKEN), for example after
# `set -a; source .env; set +a`. Each value goes to `gcloud` on stdin, so it never appears in
# the command line, the shell history or this script's output. Only the variables that are
# set are added; run it again later for the others. Terraform must have created the secrets
# first (infra/README.md, step 1).
set -euo pipefail

environment="${1:-}"
case "$environment" in
  prod) prefix="baskd" ;;
  staging) prefix="baskd-staging" ;;
  *) echo "usage: $0 prod|staging" >&2; exit 2 ;;
esac
project="${GOOGLE_CLOUD_PROJECT:-baskd-calendar}"

added=0
for pair in \
  DROPBOX_APP_KEY:dropbox-app-key \
  DROPBOX_APP_SECRET:dropbox-app-secret \
  DROPBOX_REFRESH_TOKEN:dropbox-refresh-token \
  TRELLO_API_KEY:trello-api-key \
  TRELLO_TOKEN:trello-token; do
  variable="${pair%%:*}"
  secret="$prefix-${pair#*:}"
  value="${!variable:-}"
  if [[ -z "${value//[[:space:]]/}" ]]; then
    echo "skip  $secret ($variable is not set)"
    continue
  fi
  printf '%s' "$value" | gcloud secrets versions add "$secret" --project "$project" \
    --data-file=- --quiet >/dev/null
  echo "added $secret"
  added=$((added + 1))
done
echo "$added secret version(s) added in $project."
