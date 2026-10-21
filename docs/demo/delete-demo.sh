#!/usr/bin/env bash
# Delete-event demo for TUTORIAL.md (owner: Daniel). Runs against a BASK'D server on
# http://127.0.0.1:8000 configured for Google Calendar, in an otherwise empty window on
# 2027-01-22. Each command is printed before its result so one terminal screenshot shows both.
set -euo pipefail

API=${API:-http://127.0.0.1:8000}
W='from=2027-01-22T00:00:00Z&to=2027-01-23T00:00:00Z'
JSON='Content-Type: application/json'

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
cmd() { printf '$ %s\n' "$*"; }
id_of() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

say "== Preparation: two events in the demo window (expect two ids)"
KEEP=$(curl -s "$API/events" -H "$JSON" -d '{"title":"BASKD delete demo: keep","start":"2027-01-22T11:00:00Z","end":"2027-01-22T11:30:00Z"}' | id_of)
GONE=$(curl -s "$API/events" -H "$JSON" -d '{"title":"BASKD delete demo: delete me","start":"2027-01-22T10:00:00Z","end":"2027-01-22T10:30:00Z"}' | id_of)
echo "KEEP=$KEEP"
echo "GONE=$GONE"

say "== 1. Delete one event (expect 204, no body, an X-Request-ID header)"
cmd curl -s -i -X DELETE "$API/events/$GONE"
curl -s -i -X DELETE "$API/events/$GONE" | grep -iv '^date:\|^server:\|^content-'

say "== 2. Fetch the deleted event (expect 404 event_not_found)"
cmd curl -s -i "$API/events/$GONE"
curl -s -i "$API/events/$GONE" | grep -iv '^date:\|^server:\|^content-'

say "== 3. List the window (expect 200 and only the 'keep' event)"
cmd curl -s "\"$API/events?$W\""
curl -s "$API/events?$W"
echo

say "== 4. Delete the same event again (expect 404: a second delete is not reported as a success)"
cmd curl -s -i -X DELETE "$API/events/$GONE"
curl -s -i -X DELETE "$API/events/$GONE" | grep -iv '^date:\|^server:\|^content-'

say "== Cleanup: delete the remaining event (expect 204), then the window is empty"
cmd curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/events/$KEEP"
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$API/events/$KEEP"
cmd curl -s "\"$API/events?$W\""
curl -s "$API/events?$W"
echo
