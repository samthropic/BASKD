# Cost of one operation: `GET /events`

_Drafted for Bryant Luna-Ramos (owner of the list operation) to review, correct and sign off._

We chose listing because it is the operation whose work grows with input size. Everything
below describes the code at the time of writing (`api/events.py::list_events`,
`api/cursors.py`, `providers/google.py::list_events`, `providers/memory.py::list_events`).
Where we state an assumption rather than something we measured or read in our own code, we
say so.

## Inputs and sizes

| Symbol | Meaning |
| --- | --- |
| `L` | the requested page size, `limit` (1–250, default 50) |
| `M` | events that overlap the requested window `[from, to)` |
| `N` | all events stored in the calendar, inside the window or not |
| `k` | items Google returns in one page (`k ≤ L`) |
| `t` | length of the cursor (a few hundred bytes; it is Google's page token plus the window) |

## One request against Google (production)

| Step | Where | Work | Memory |
| --- | --- | --- | --- |
| Validate `from`, `to`, `limit`, `cursor` | `models.py::ListEventsQuery` | O(1) | O(1) |
| Unwrap the cursor and compare its window | `api/cursors.py::unwrap_cursor` | O(t): base64 + JSON decode | O(t) |
| Build the request | `google.py::list_events` | O(1) | O(1) |
| **One `events.list` call** with `maxResults=L`, `singleEvents=true`, `orderBy=startTime` | Google | **Delegated: unknown to us** | none of ours |
| Parse the response JSON | the SDK | O(size of response) ≈ O(k) | O(k) |
| Drop cancelled items, map each to our `Event` | `google.py::event_from_google` | O(k) | O(k) |
| Wrap the next-page token | `api/cursors.py::wrap_cursor` | O(t) | O(t) |
| Serialize the page | FastAPI/pydantic | O(k) | O(k) |

**Local cost per request: O(k + t) time and memory, so O(L) since `k ≤ L` and `t` is
small.** It does not depend on `N` or `M`.

**Provider calls per request: exactly one `events.list`.** We never retry
(`num_retries=0`). Separately, `google-auth` makes **one extra call to Google's token
endpoint** when the service account's cached access token is missing or expired (the first
request after startup and then roughly once an hour; the hour is Google's documented
token lifetime, an assumption we have not measured). The token is cached on the shared
credentials object, not per request.

**Work delegated to Google:** filtering by the window, expanding recurring events into
instances, sorting by start time and paging. We cannot see how Google does this: we do not
know whether it touches only the `k` returned events, all `M` in the window, or more (for
example all instances of a long recurring series). A slow list request therefore does not
tell us whether the time went to Google's query, the network, or our own (small) work;
telling those apart would need timing around `request.execute` separately from the request
as a whole.

### Returned vs fetched vs inspected

- **Fetched:** `k` items in Google's page, `k ≤ L`. Google may return a short page
  (even an empty one) with a `nextPageToken`, so `k < L` does not mean the listing is done.
  Only `next_cursor: null` means that.
- **Returned:** `k` minus cancelled items. With `showDeleted=false` Google should not send
  cancelled items; we filter defensively, so normally returned = fetched.
- **Inspected:** everything Google looks at to produce the page. Unknown to us, see above.

### A full traversal

Reading all `M` events in a window takes at least `⌈M / L⌉` requests to our API and the same
number of `events.list` calls (more if Google returns short pages), plus at most a token
refresh. Our local work is O(M) in total, and O(L) memory at any one time. Raising `limit`
reduces calls (and per-call latency overhead) at the cost of bigger responses. The cap of
250 is ours; Google allows up to 2500.

## One request against the in-memory provider (tests and local development)

```python
ordered = sorted(self._events.values(), key=lambda event: (event.start, event.id))  # O(N log N)
matching = [e for e in ordered if _overlaps(e, from, to)]                            # O(N)
page = matching[offset : offset + limit]                                             # O(L)
```

**O(N log N) time and O(N) extra memory per request, and zero provider calls.** The fake
re-sorts the *whole calendar*, not just the window, on every page, so a full traversal costs
O((M / L) · N log N). That is fine for a test double holding a few events, and it keeps the
fake obviously correct, but it is the reason the fake must never be used as a production
store. A sorted index (or keeping events in start order on insert) would bring a page to
O(log N + L) if it ever mattered. Its cursor is a plain offset, so the traversal is
consistent only while the calendar does not change between pages. The real provider gives
no stronger guarantee: a page token is not a snapshot.

## Assumptions

- Google's internal cost of `events.list` is unknown, so "one call" is a count, not a cost.
- Token lifetime of about an hour is from Google's documentation, not measured.
- Response size grows linearly with `k`, because each event is a bounded object
  (title ≤ 1024, description ≤ 8192 characters for events we create; events created
  elsewhere could carry longer text, which we pass through).
- No benchmark was run; the spec does not require one.
