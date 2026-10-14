#!/usr/bin/env python3
"""Walk the thin slice against a *running* BASK'D server and print every step.

    make run            # in one terminal (uses .env; or `make run-memory`)
    make demo           # in another; or: python scripts/demo.py http://127.0.0.1:8000

Standard library only, so it also works from a fresh checkout without the dev environment.
Exit code is non-zero if any step does not behave as documented.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def call(
    method: str, url: str, body: dict[str, Any] | None = None
) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None, dict(error.headers)


def step(title: str, status: int, expected: int, payload: Any) -> None:
    marker = "ok " if status == expected else "FAIL"
    print(f"[{marker}] {title}: HTTP {status} (expected {expected})")
    if payload is not None:
        print("       " + json.dumps(payload, indent=None)[:400])
    if status != expected:
        raise SystemExit(1)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def main() -> None:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL).rstrip("/")
    marker = uuid4().hex[:8]
    start = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
    end = start + timedelta(minutes=45)

    status, body, _ = call("GET", f"{base}/health")
    step("health", status, 200, body)
    print(f"       provider = {body['provider']}")

    status, event, headers = call(
        "POST",
        f"{base}/events",
        {
            "title": f"BASK'D demo {marker}",
            "start": iso(start),
            "end": iso(end),
            "description": "Created by scripts/demo.py; safe to delete.",
            "location": "Room 101",
        },
    )
    step("create event", status, 201, event)
    print(f"       Location = {headers.get('Location') or headers.get('location')}")
    event_id = event["id"]

    status, fetched, _ = call("GET", f"{base}/events/{event_id}")
    step("get event", status, 200, fetched)
    assert fetched == event, "GET must return exactly what POST returned"

    window = urllib.parse.urlencode(
        {"from": iso(start - timedelta(hours=1)), "to": iso(end + timedelta(hours=1))}
    )
    status, page, _ = call("GET", f"{base}/events?{window}")
    step(
        "list events in window",
        status,
        200,
        {"count": len(page["items"]), "next_cursor": page["next_cursor"]},
    )
    assert event_id in {item["id"] for item in page["items"]}, "created event must be listed"

    status, body, _ = call(
        "POST", f"{base}/events", {"title": "bad", "start": iso(end), "end": iso(start)}
    )
    step("reject end before start", status, 422, body)

    status, moved, _ = call(
        "PUT",
        f"{base}/events/{event_id}",
        {
            "title": f"BASK'D demo {marker} (moved)",
            "start": iso(start + timedelta(hours=2)),
            "end": iso(end + timedelta(hours=2)),
        },
    )
    step("replace event", status, 200, moved)
    assert moved["description"] is None, "omitted optional fields are cleared on PUT"

    status, _, _ = call("DELETE", f"{base}/events/{event_id}")
    step("delete event", status, 204, None)

    status, body, _ = call("GET", f"{base}/events/{event_id}")
    step("get after delete", status, 404, body)

    status, body, _ = call("DELETE", f"{base}/events/{event_id}")
    step("delete again", status, 404, body)

    print("\nAll steps behaved as documented.")


if __name__ == "__main__":
    main()
