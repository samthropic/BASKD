#!/usr/bin/env bash
# Get-event demo for TUTORIAL.md (owner: Arda). Runs against a BASK'D server on
# http://127.0.0.1:8000 configured for Google Calendar. Creates one event in an otherwise
# empty window on 2027-01-29 and deletes it at the end. Each command is printed before its
# result so one terminal screenshot shows both.
set -euo pipefail

API=${API:-http://127.0.0.1:8000}
W='from=2027-01-29T00:00:00Z&to=2027-01-30T00:00:00Z'
JSON='Content-Type: application/json'
MISSING=baskd-demo-no-such-event

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
cmd() { printf '$ %s\n' "$*"; }
id_of() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

say "== Preparation: one event sent with a New York offset (expect an id)"
ID=$(curl -s "$API/events" -H "$JSON" -d '{"title":"BASKD get demo","start":"2027-01-29T10:00:00-05:00","end":"2027-01-29T10:30:00-05:00","location":"NYU Tandon"}' | id_of)
echo "ID=$ID"

say "== 1. Get the event (expect 200, the event as stored, times converted to UTC: 15:00Z-15:30Z)"
cmd curl -s -i "$API/events/$ID"
curl -s -i "$API/events/$ID" | grep -iv '^date:\|^server:\|^content-'
echo

say "== 2. Get an id that does not exist (expect 404 event_not_found and an X-Request-ID header)"
cmd curl -s -i "$API/events/$MISSING"
curl -s -i "$API/events/$MISSING" | grep -iv '^date:\|^server:\|^content-'
echo

say "== Cleanup: delete the event (expect 204), then the window is empty"
cmd curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/events/$ID"
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$API/events/$ID"
cmd curl -s "\"$API/events?$W\""
curl -s "$API/events?$W"
echo
