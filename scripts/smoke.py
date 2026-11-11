#!/usr/bin/env python3
"""Smoke-check a deployed BASK'D against the real calendar, then delete what it made.

    BASKD_SMOKE_TOKEN=$(gcloud auth print-identity-token) python scripts/smoke.py "$URL"

Runs health, create, get, replace, delete, and a get that must now be 404. If a step fails
after the event was created, the event is still deleted. The token (a Google identity token
for the service's audience) is sent as a bearer token and never printed. Exit code 0 only if
every step behaved as documented; the deploy workflow promotes a release only then.

Standard library only, so the workflow runs it without installing the project.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


class SmokeFailure(Exception):
    pass


def call(
    method: str, url: str, token: str, body: dict[str, Any] | None = None
) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw[:200].decode(errors="replace")
        return error.code, payload, dict(error.headers)


def check(name: str, status: int, expected: int, payload: Any) -> None:
    ok = status == expected
    print(f"[{'ok ' if ok else 'FAIL'}] {name}: HTTP {status} (expected {expected})")
    if not ok:
        print("       " + json.dumps(payload)[:300])
        raise SmokeFailure(name)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run(base: str, token: str, label: str) -> None:
    status, body, _ = call("GET", f"{base}/health", token)
    check("health", status, 200, body)

    start = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    title = f"BASK'D smoke {label}"
    status, created, headers = call(
        "POST",
        f"{base}/events",
        token,
        {"title": title, "start": iso(start), "end": iso(start + timedelta(minutes=30))},
    )
    check("create", status, 201, created)
    event_id = created["id"]
    try:
        if "Location" not in headers and "location" not in headers:
            raise SmokeFailure("create: no Location header")

        status, got, _ = call("GET", f"{base}/events/{event_id}", token)
        check("get", status, 200, got)
        if got.get("title") != title:
            raise SmokeFailure(f"get: title {got.get('title')!r}, expected {title!r}")

        new_title = f"{title} (replaced)"
        status, replaced, _ = call(
            "PUT",
            f"{base}/events/{event_id}",
            token,
            {
                "title": new_title,
                "start": iso(start + timedelta(hours=1)),
                "end": iso(start + timedelta(hours=1, minutes=30)),
            },
        )
        check("replace", status, 200, replaced)
        if replaced.get("title") != new_title:
            raise SmokeFailure(f"replace: title {replaced.get('title')!r}, expected {new_title!r}")
    finally:
        status, body, _ = call("DELETE", f"{base}/events/{event_id}", token)
        check("delete", status, 204, body)

    status, body, _ = call("GET", f"{base}/events/{event_id}", token)
    check("get after delete", status, 404, body)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    token = os.environ.get("BASKD_SMOKE_TOKEN", "")
    if not token:
        print("BASKD_SMOKE_TOKEN is not set")
        return 2
    label = os.environ.get("BASKD_SMOKE_LABEL") or uuid4().hex[:8]
    try:
        run(sys.argv[1].rstrip("/"), token, label)
    except SmokeFailure as failure:
        print(f"smoke check FAILED at {failure}")
        return 1
    print("smoke check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
