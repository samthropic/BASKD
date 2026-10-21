# BASK'D demo: the workflow against Google Calendar

Each section is one operation, run by its owner against the real Google Calendar through
`curl`. Every section says what we expected and shows what actually came back. The output is
copied from a real run; only the parts noted below were shortened.

Setup for every section: configure `.env` as in [`docs/HUMAN_STEPS.md`](docs/HUMAN_STEPS.md),
then `make run` (the service listens on `http://127.0.0.1:8000`). Check
`curl -s http://127.0.0.1:8000/health` reports `"provider":"google"`.

## List events: `GET /events` (Bryant Luna-Ramos)

Run on 2026-10-20, Linux, commit `3153e3b` (`arda/milestone-1`), provider `google`.

**What this shows:** listing a time window one page at a time, following `next_cursor` to
the end, and the service refusing a cursor that is reused with a different window.

**Preparation.** I created three events in an otherwise empty window on Jan 15, 2027 (09:00,
11:00 and 13:00 UTC, 30 minutes each), so the listing has a known answer:

```bash
for h in 09 11 13; do
  curl -s http://127.0.0.1:8000/events -H 'Content-Type: application/json' \
    -d "{\"title\":\"BASKD list demo $h:00\",\"start\":\"2027-01-15T$h:00:00Z\",\"end\":\"2027-01-15T$h:30:00Z\"}"
done
```

Shortened in the output below: `web_link` (Google's link encodes the calendar id) and the
cursors (a few hundred characters each). Copy the full `next_cursor` from your own response.

### 1. First page

**Expected:** `200`, exactly one event (the earliest, 09:00), and a non-null `next_cursor`
because two more events match.

```console
$ curl -s -i 'http://127.0.0.1:8000/events?from=2027-01-15T00:00:00Z&to=2027-01-16T00:00:00Z&limit=1'
HTTP/1.1 200 OK
content-type: application/json

{
    "items": [
        {
            "id": "c70tf8lk7kap6du46ce118r16c",
            "title": "BASKD list demo 09:00",
            "start": "2027-01-15T09:00:00Z",
            "end": "2027-01-15T09:30:00Z",
            "all_day": false,
            "description": null,
            "location": null,
            "web_link": "https://www.google.com/calendar/event?eid=…"
        }
    ],
    "next_cursor": "eyJjIjoiRWl3S0toSW9DZ1lJa01Dbj…"
}
```

**Actual:** as expected.

### 2. Next page

**Expected:** `200`, the 11:00 event, and another cursor.

```console
$ curl -s -i "http://127.0.0.1:8000/events?from=2027-01-15T00:00:00Z&to=2027-01-16T00:00:00Z&limit=1&cursor=$CURSOR_1"
HTTP/1.1 200 OK
content-type: application/json

{
    "items": [
        {
            "id": "usnrbqg1igel3nl9bh2igdv910",
            "title": "BASKD list demo 11:00",
            "start": "2027-01-15T11:00:00Z",
            "end": "2027-01-15T11:30:00Z",
            "all_day": false,
            "description": null,
            "location": null,
            "web_link": "https://www.google.com/calendar/event?eid=…"
        }
    ],
    "next_cursor": "eyJjIjoiRWl3S0toSW9DZ1lJc1Bpbj…"
}
```

**Actual:** as expected.

### 3. Last page

**Expected:** `200`, the 13:00 event, and `next_cursor: null`. Null is the only signal that the
listing is finished; a short page on its own is not.

```console
$ curl -s -i "http://127.0.0.1:8000/events?from=2027-01-15T00:00:00Z&to=2027-01-16T00:00:00Z&limit=1&cursor=$CURSOR_2"
HTTP/1.1 200 OK
content-type: application/json

{
    "items": [
        {
            "id": "79l3dn4162mi87vin3nrkiiam8",
            "title": "BASKD list demo 13:00",
            "start": "2027-01-15T13:00:00Z",
            "end": "2027-01-15T13:30:00Z",
            "all_day": false,
            "description": null,
            "location": null,
            "web_link": "https://www.google.com/calendar/event?eid=…"
        }
    ],
    "next_cursor": null
}
```

**Actual:** as expected. Three pages, three events, in start order.

### 4. Failure: a cursor reused with another window

**Expected:** `400 invalid_request`. A cursor only continues the listing it came from;
continuing with a different `from` would silently mix two listings. This is checked before
Google is called, so nothing is fetched.

```console
$ curl -s -i "http://127.0.0.1:8000/events?from=2027-01-15T10:00:00Z&to=2027-01-16T00:00:00Z&limit=1&cursor=$CURSOR_2"
HTTP/1.1 400 Bad Request
content-type: application/json

{
    "error": {
        "code": "invalid_request",
        "message": "Cursor was issued for a different 'from'/'to'; repeat the original query or start again without a cursor"
    }
}
```

**Actual:** as expected.

**Cleanup.** I deleted the three events (`DELETE /events/{id}` for each id above), then
confirmed the window is empty again:

```console
$ curl -s 'http://127.0.0.1:8000/events?from=2027-01-15T00:00:00Z&to=2027-01-16T00:00:00Z'
{"items":[],"next_cursor":null}
```

This run predates [#20](https://github.com/samthropic/BASKD/pull/20), so the responses have
no `X-Request-ID` header yet. After #20 merges, step 4 also returns one, and the server logs a
`request_failed` line with `"provider_involved": false`.
