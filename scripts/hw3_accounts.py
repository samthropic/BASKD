#!/usr/bin/env python3
"""Put the HW3 Dropbox and Trello credentials into Secret Manager, interactively.

    python scripts/hw3_accounts.py prod            # or: staging
    python scripts/hw3_accounts.py prod --only trello

Walks through ``docs/HUMAN_STEPS.md`` §8 in the terminal. Every value is typed with hidden
input, checked against Dropbox or Trello, and piped straight to
``gcloud secrets versions add``: nothing is printed, written to disk or kept in shell history.

* Dropbox: the refresh token comes from Dropbox's own code flow (open a link, approve, paste
  the code), so no redirect URI and no storage package are needed. Team 3's and Team 1's
  packages use the same three values.
* Trello: after the token, paste the board's URL and pick the list for prep issues. Its id is
  not secret; the script prints the ``trello_list_id`` line for the ``.tfvars``.

Run ``terraform apply`` first: it creates the (empty) secrets. Standard library plus ``gcloud``.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

DROPBOX_SCOPES = {
    "account_info.read",
    "files.metadata.read",
    "files.metadata.write",
    "files.content.read",
    "files.content.write",
}


class SetupError(Exception):
    pass


def request(
    method: str, url: str, headers: dict[str, str], body: bytes | None = None
) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, None


def ask(prompt: str) -> str:
    for _ in range(3):
        value = getpass.getpass(f"{prompt} (hidden, paste then Enter): ").strip()
        if value:
            print(f"  got it ({len(value)} characters)")
            return value
        print("  nothing was entered; paste it again")
    raise SetupError(f"{prompt}: nothing entered")


def open_link(what: str, url: str) -> None:
    print(f"Opening {what} in your browser.")
    if not webbrowser.open(url):
        print(f"Could not open a browser; open this link yourself:\n  {url}")


class Secrets:
    def __init__(self, environment: str, project: str) -> None:
        self.prefix = "baskd" if environment == "prod" else "baskd-staging"
        self.project = project

    def name(self, suffix: str) -> str:
        return f"{self.prefix}-{suffix}"

    def check_exist(self, suffixes: list[str]) -> None:
        for suffix in suffixes:
            result = subprocess.run(
                ["gcloud", "secrets", "describe", self.name(suffix), "--project", self.project],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise SetupError(
                    f"Secret {self.name(suffix)} does not exist in {self.project}. "
                    "Run terraform apply for this environment first (infra/README.md)."
                )

    def add(self, suffix: str, value: str) -> None:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "add",
                self.name(suffix),
                "--project",
                self.project,
                "--data-file=-",
            ],
            input=value,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SetupError(f"gcloud could not add a version to {self.name(suffix)}")
        print(f"  stored a new version of {self.name(suffix)}")


def dropbox(secrets: Secrets) -> None:
    secrets.check_exist(["dropbox-app-key", "dropbox-app-secret", "dropbox-refresh-token"])
    print(
        "\n== Dropbox ==\n"
        "1. In the App Console (opening now), Create app: Scoped access, App folder,\n"
        "   any name (e.g. baskd-hw3-test).\n"
        "2. Permissions tab: tick account_info.read, files.metadata.read,\n"
        "   files.metadata.write, files.content.read, files.content.write, then Submit.\n"
        "   (Do this before step 4: a token only gets the scopes ticked when it is made.)\n"
        "3. Settings tab: copy the App key and the App secret (click Show)."
    )
    open_link("the Dropbox App Console", "https://www.dropbox.com/developers/apps")
    key = ask("Dropbox App key")
    secret = ask("Dropbox App secret")

    query = urllib.parse.urlencode(
        {"client_id": key, "response_type": "code", "token_access_type": "offline"}
    )
    print("4. Approve the app in the browser, then copy the access code Dropbox shows.")
    open_link("Dropbox's approval page", f"https://www.dropbox.com/oauth2/authorize?{query}")
    code = ask("Dropbox access code")

    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    status, token = request(
        "POST",
        "https://api.dropboxapi.com/oauth2/token",
        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({"grant_type": "authorization_code", "code": code}).encode(),
    )
    if status != 200 or not isinstance(token, dict) or "refresh_token" not in token:
        reason = token.get("error_description") if isinstance(token, dict) else None
        raise SetupError(f"Dropbox did not issue a refresh token (HTTP {status}: {reason})")
    missing = DROPBOX_SCOPES - set(str(token.get("scope", "")).split())
    if missing:
        raise SetupError(
            "The token lacks " + ", ".join(sorted(missing)) + ". Tick them on the Permissions "
            "tab, Submit, and run this again (the old token can be ignored)."
        )
    status, _ = request(
        "POST",
        "https://api.dropboxapi.com/2/users/get_current_account",
        {"Authorization": f"Bearer {token['access_token']}"},
    )
    if status != 200:
        raise SetupError(f"Dropbox rejected the new token (HTTP {status})")
    print("  Dropbox accepted the token and it has all five scopes.")

    secrets.add("dropbox-app-key", key)
    secrets.add("dropbox-app-secret", secret)
    secrets.add("dropbox-refresh-token", str(token["refresh_token"]))


def trello(secrets: Secrets) -> str:
    secrets.check_exist(["trello-api-key", "trello-token"])
    print(
        "\n== Trello ==\n"
        "1. Make a board for the test (any name). Its default lists are fine.\n"
        "2. In the Power-Up admin portal (opening now): New, fill in the form (any workspace,\n"
        "   any URL), then open 'API key' and Generate. Copy the API key."
    )
    open_link("the Trello Power-Up admin portal", "https://trello.com/power-ups/admin")
    key = ask("Trello API key")

    query = urllib.parse.urlencode(
        {
            "expiration": "never",
            "scope": "read,write",
            "response_type": "token",
            "name": "BASKD HW3",
            "key": key,
        }
    )
    print("3. Click Allow in the browser, then copy the token it shows.")
    open_link("Trello's approval page", f"https://trello.com/1/authorize?{query}")
    token = ask("Trello token")
    auth = {"Authorization": f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'}
    status, _ = request("GET", "https://api.trello.com/1/members/me?fields=id", auth)
    if status != 200:
        raise SetupError(f"Trello rejected the key and token (HTTP {status})")
    print("  Trello accepted the key and token.")

    board_url = input("4. Paste the board's URL (https://trello.com/b/...): ").strip()
    match = re.search(r"trello\.com/b/([A-Za-z0-9]+)", board_url)
    if not match:
        raise SetupError("That is not a board URL (https://trello.com/b/<id>/...)")
    status, lists = request(
        "GET", f"https://api.trello.com/1/boards/{match.group(1)}/lists?fields=name", auth
    )
    if status != 200 or not isinstance(lists, list) or not lists:
        raise SetupError(f"Could not read that board's lists (HTTP {status})")
    for number, entry in enumerate(lists, 1):
        print(f"   {number}. {entry['name']}")
    choice = input("   Which list should prep issues go on? Number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(lists):
        raise SetupError("Pick one of the numbers shown")
    list_id = str(lists[int(choice) - 1]["id"])

    secrets.add("trello-api-key", key)
    secrets.add("trello-token", token)
    return list_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("environment", choices=["prod", "staging"])
    parser.add_argument("--only", choices=["dropbox", "trello"])
    args = parser.parse_args()
    secrets = Secrets(args.environment, os.environ.get("GOOGLE_CLOUD_PROJECT", "baskd-calendar"))
    try:
        if args.only != "trello":
            dropbox(secrets)
        if args.only != "dropbox":
            list_id = trello(secrets)
            print(
                f"\nDone. Put this in infra/{args.environment}.tfvars (not secret):\n"
                f'  trello_list_id = "{list_id}"'
            )
        else:
            print("\nDone.")
    except SetupError as error:
        print(f"\nStopped: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped; nothing more was stored.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
