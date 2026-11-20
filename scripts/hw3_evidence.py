#!/usr/bin/env python3
"""Run the HW3 workflow on the deployed service and confirm its records in each provider.

    export BASKD_SMOKE_TOKEN=$(gcloud auth print-identity-token)
    python scripts/hw3_evidence.py "$URL" compose   # team3 storage + team4 issues
    python scripts/hw3_evidence.py "$URL" swap      # team1 storage + team4 issues
    python scripts/hw3_evidence.py "$URL" failure   # issues = failing

Each run reads ``/health`` (which implementations are live), sends one
``POST /workflows/meeting-prep`` and prints a Markdown section with the request, the response
and what each provider holds afterwards. Paste the sections into issue #68 (or pass
``--out FILE`` to append them). The records are kept so graders can look them up.

Provider checks: the calendar event through ``GET /events/{id}``, which reads Google; the
Dropbox file and the Trello card through their own APIs, when ``DROPBOX_APP_KEY``,
``DROPBOX_APP_SECRET``, ``DROPBOX_REFRESH_TOKEN``, ``TRELLO_API_KEY`` and ``TRELLO_TOKEN``
are exported (the same values ``scripts/add_workflow_secrets.sh`` stores). Credentials go in
headers or request bodies and are never printed.

Exit code 0 only if the run behaved as documented for its label: ``compose`` and ``swap``
need 201 and every record found; ``failure`` needs an error that names ``failed_step``.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

#: What /health should report for each label. A mismatch is reported, not fatal: the label
#: names the demo, and the evidence shows the configuration it actually ran with.
EXPECTED_CONFIG = {
    "compose": ("team3", "team4"),
    "swap": ("team1", "team4"),
    "failure": (None, "failing"),
}


@dataclass
class Evidence:
    label: str
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def block(self, payload: Any) -> None:
        self.lines += ["```json", json.dumps(payload, indent=2), "```"]

    def fail(self, problem: str) -> None:
        self.problems.append(problem)
        self.add(f"- **Not as documented:** {problem}")


def call(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, raw[:300].decode(errors="replace")


def api(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    return call(method, url, headers, body)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def check_dropbox(evidence: Evidence, document: dict[str, Any]) -> None:
    key, secret, refresh = (
        os.environ.get("DROPBOX_APP_KEY"),
        os.environ.get("DROPBOX_APP_SECRET"),
        os.environ.get("DROPBOX_REFRESH_TOKEN"),
    )
    if not (key and secret and refresh):
        evidence.add("- Dropbox: not checked here (DROPBOX_* not exported); see the screenshot")
        return
    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh})
    status, token = call(
        "POST",
        "https://api.dropboxapi.com/oauth2/token",
        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        form.encode(),
    )
    if status != 200 or not isinstance(token, dict) or "access_token" not in token:
        evidence.fail(f"Dropbox refused the refresh token (HTTP {status})")
        return
    target = document.get("id") or document["path"]
    status, meta = call(
        "POST",
        "https://api.dropboxapi.com/2/files/get_metadata",
        {"Authorization": f"Bearer {token['access_token']}", "Content-Type": "application/json"},
        json.dumps({"path": target}).encode(),
    )
    if status == 200 and isinstance(meta, dict):
        evidence.add(
            f"- Dropbox (`files/get_metadata`): `{meta.get('path_display')}`, "
            f"{meta.get('size')} bytes, modified {meta.get('server_modified')}"
        )
    else:
        evidence.fail(f"Dropbox has no file at `{target}` (HTTP {status})")


def check_trello(evidence: Evidence, issue: dict[str, Any]) -> None:
    key, token = os.environ.get("TRELLO_API_KEY"), os.environ.get("TRELLO_TOKEN")
    if not (key and token):
        evidence.add("- Trello: not checked here (TRELLO_* not exported); see the screenshot")
        return
    auth = f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'
    card_id = urllib.parse.quote(issue["id"], safe="")
    status, card = call(
        "GET",
        f"https://api.trello.com/1/cards/{card_id}?fields=name,idList,shortUrl,closed",
        {"Authorization": auth},
    )
    if status != 200 or not isinstance(card, dict):
        evidence.fail(f"Trello has no card `{issue['id']}` (HTTP {status})")
        return
    on_list = card.get("idList") == os.environ.get("TRELLO_LIST_ID", card.get("idList"))
    evidence.add(
        f'- Trello (`GET /1/cards/{{id}}`): "{card.get("name")}" on list `{card.get("idList")}`'
        f"{'' if on_list else ' (not TRELLO_LIST_ID!)'}, {card.get('shortUrl')}"
    )
    if card.get("name") != issue["title"]:
        evidence.fail("the Trello card's name differs from the issue title we returned")


def check_event(evidence: Evidence, base: str, token: str, event_id: str) -> None:
    status, event = api("GET", f"{base}/events/{urllib.parse.quote(event_id, safe='')}", token)
    if status == 200 and isinstance(event, dict):
        evidence.add(
            f"- Google Calendar (`GET /events/{{id}}`, read from Google): "
            f'"{event.get("title")}", {event.get("start")} to {event.get("end")}'
        )
    else:
        evidence.fail(f"the calendar has no event `{event_id}` (HTTP {status})")


def run(base: str, token: str, label: str) -> Evidence:
    evidence = Evidence(label)
    now = datetime.now(UTC).replace(microsecond=0)
    evidence.add(f"## `{label}`: {iso(now)}")
    evidence.add()

    status, health = api("GET", f"{base}/health", token)
    evidence.add(f"Configuration (`GET /health`, HTTP {status}):")
    evidence.block(health)
    storage, issues = EXPECTED_CONFIG[label]
    if isinstance(health, dict):
        if storage and health.get("workflow_storage") != storage:
            evidence.fail(f"expected workflow_storage={storage} for `{label}`")
        if health.get("workflow_issues") != issues:
            evidence.fail(f"expected workflow_issues={issues} for `{label}`")

    start = (now + timedelta(days=14)).replace(hour=15, minute=0, second=0)
    body = {
        "title": f"HW3 evidence {label} {uuid4().hex[:6]}",
        "start": iso(start),
        "end": iso(start + timedelta(minutes=30)),
        "agenda": f"1. Show the `{label}` run of the HW3 workflow\n2. Check each provider",
    }
    evidence.add()
    evidence.add("Request (`POST /workflows/meeting-prep`):")
    evidence.block(body)
    status, result = api("POST", f"{base}/workflows/meeting-prep", token, body)
    evidence.add()
    evidence.add(f"Response: HTTP {status}")
    evidence.block(result)
    evidence.add()
    evidence.add("What the providers hold afterwards:")
    evidence.add()

    if status == 201 and isinstance(result, dict):
        if label == "failure":
            evidence.fail("the failure run succeeded; is `workflow_issues` set to `failing`?")
        check_event(evidence, base, token, result["event"]["id"])
        check_dropbox(evidence, result["document"])
        check_trello(evidence, result["issue"])
        return evidence

    error = result.get("error", {}) if isinstance(result, dict) else {}
    failed_step = error.get("failed_step")
    if label != "failure":
        evidence.fail(f"expected 201, got HTTP {status} (failed_step={failed_step})")
    elif not failed_step:
        evidence.fail("the error does not name `failed_step`")
    completed = {step.get("step"): step.get("id") for step in error.get("completed") or []}
    if "create_event" in completed:
        check_event(evidence, base, token, completed["create_event"])
    if failed_step:
        evidence.add(
            f"- `{failed_step}` failed and left nothing behind; finished steps: "
            f"{', '.join(completed) or 'none'}. Resume by resending the body with `event_id`."
        )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("url", help="service URL, e.g. $(terraform output -raw service_url)")
    parser.add_argument("label", choices=sorted(EXPECTED_CONFIG))
    parser.add_argument("--out", help="also append the Markdown section to this file")
    args = parser.parse_args()
    token = os.environ.get("BASKD_SMOKE_TOKEN")
    if not token:
        print("Set BASKD_SMOKE_TOKEN=$(gcloud auth print-identity-token)", file=sys.stderr)
        return 2

    evidence = run(args.url.rstrip("/"), token, args.label)
    text = "\n".join(evidence.lines) + "\n"
    print(text)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if evidence.problems:
        print("NOT AS DOCUMENTED: " + "; ".join(evidence.problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
