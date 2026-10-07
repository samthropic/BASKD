# Human steps: credentials, access and permissions

Everything in this file requires a person with a browser and the right account. None of it is
automated and none of it should be: these are the decisions and secrets a team is accountable
for. Do them **once per team**, early (the handout: "Verify access before assigning substantial
implementation work. Raise access or cost problems with staff early.").

Estimated time: 20-30 minutes for §1-§4 if nothing is blocked by an organisation policy.

## 0. Who does what (fill in)

| Role | Person | Why it matters |
| --- | --- | --- |
| Google Cloud project owner | Arda Dinc (project `baskd-calendar`) | Can create/delete the service account and its keys; should be a **personal** Google account (see §1 caveat) |
| Test-calendar owner | Arda Dinc ("BASK'D test calendar") | The calendar lives in their Google account; they can revoke the robot's access at any time |
| Key custodians | all developers | Each has the key file locally under `secrets/`; nobody has it in git, chat, or email |
| GitHub repository admin | _TBD_ | Sets repository secrets (§4) and branch protection (§5) |
| Staff contact for access/cost problems | course staff via `#help` | Raise early, as the handout asks |

Record who holds these roles in `docs/TEAM_AGREEMENT.md`.

## 1. Google Cloud: project, API, service account, key

> **Caveat first.** University or company Google accounts are often under an organisation
> policy (`iam.disableServiceAccountKeyCreation`) that blocks creating service-account keys,
> and Google Workspace admins often restrict sharing calendars with outside accounts. **Use a
> personal Gmail account** for both the Cloud project and the test calendar; it avoids both
> problems. Nothing here costs money: the Calendar API has no charge and a generous free quota.

1. Go to <https://console.cloud.google.com/> signed in with the personal account. Create a new
   project, e.g. `baskd-calendar`. (A project is just a container for the API and the robot.)
2. **Enable the API:** menu → *APIs & Services* → *Library* → search "Google Calendar API" →
   *Enable*.
3. **Create the robot identity:** *IAM & Admin* → *Service Accounts* → *Create service
   account*. Name: `baskd-calendar`. Skip the optional "grant access" steps; the robot needs
   **no IAM roles** (Calendar access is granted by sharing a calendar with it, not by IAM).
   Note the generated email, which looks like
   `baskd-calendar@baskd-calendar.iam.gserviceaccount.com`.
4. **Create a key:** open the service account → *Keys* → *Add key* → *Create new key* →
   *JSON* → *Create*. A file downloads. Move it to the repo as
   `secrets/service-account.json` (the `secrets/` directory is git-ignored; `git status` must
   never show it). Share it with teammates through the team password manager, not chat.

If step 4 fails with a policy error, you are in an organisation-managed account: switch to a
personal account, or ask staff. Fallback if service accounts are impossible for the whole
team: an OAuth "Desktop app" client with a one-time browser consent producing a refresh
token. That requires a code change in `baskd/providers/google.py::load_credentials`; open an
issue before going down that path.

## 2. The shared test calendar

1. Go to <https://calendar.google.com/> as the calendar owner. In the left sidebar, *Other
   calendars* → **+** → *Create new calendar*. Name: `BASK'D test calendar`. Create.
2. Open the new calendar's *Settings and sharing*. Under **Share with specific people or
   groups** → *Add people* → paste the service-account email from §1.3 → permission **Make
   changes to events** → *Send*. (Not "Make changes and manage sharing": least privilege.)
3. Optionally add teammates with *See all event details* so everyone can watch the demo.
4. Scroll to **Integrate calendar** and copy the **Calendar ID** (ends in
   `@group.calendar.google.com`). That value is `BASKD_GOOGLE_CALENDAR_ID`.

Rules for this calendar: it is **disposable**. Tests create and delete events in it; anybody
may delete anything in it; never share a personal calendar with the robot.

## 3. Verify locally (every developer)

```bash
cp .env.example .env
# edit .env: BASKD_PROVIDER=google, BASKD_GOOGLE_CALENDAR_ID=<from §2.4>,
#            BASKD_GOOGLE_CREDENTIALS_FILE=secrets/service-account.json
uv sync --locked
uv run pytest -m integration -ra       # expect 4 passed, 0 skipped
```

If you see:

- `provider_auth_error ... Calendar not found or not shared` → §2.2 was skipped or the ID is
  wrong.
- `Google rejected the service-account credentials` → the key file is corrupt/revoked, or the
  machine clock is off by minutes (JWT signing is time-sensitive).
- `FileNotFoundError: Google credentials file not found` → path in `.env` is relative to the
  directory you run from.
- Everything is `SKIPPED` → `.env` is not being read (wrong directory) or `BASKD_PROVIDER` is
  not `google`.

Then `make run` and `make demo`, and look at the calendar in the browser while the demo runs.

## 4. GitHub Actions secrets (repository admin)

Repository → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*:

| Secret | Value |
| --- | --- |
| `BASKD_GOOGLE_CREDENTIALS_JSON` | The **entire contents** of `secrets/service-account.json` |
| `BASKD_GOOGLE_CALENDAR_ID` | The calendar ID from §2.4 |

Then run the CI workflow manually once (*Actions* → *CI* → *Run workflow*) and confirm the
"Integration (real Google Calendar)" job passes. Until the secrets exist, that job prints a
notice and skips; nothing else is affected.

## 5. Branch protection (repository admin)

Repository → *Settings* → *Branches* (or *Rules → Rulesets*) → protect `main`:

- Require a pull request before merging, with **1 approval**, and dismiss stale approvals.
- Require status checks to pass: `Lint, types, unit tests` and `Docker image builds and
  serves /health` (the integration job cannot be required because it legitimately skips on
  forks).
- Require branches to be up to date before merging; block force-pushes and deletions.

Also enable *Settings → General → Pull Requests → Allow squash merging* (our merge strategy)
and consider disabling merge commits.

## 6. Security hygiene

- **What the key can do:** act as the robot on Google APIs within the `calendar.events`
  scope. Its blast radius is exactly the calendars shared with it (one, if you follow §2).
- **Where the key may live:** developer laptops under `secrets/`, the team password manager,
  GitHub Actions secrets. Nowhere else. Never paste it into an issue, a PR, Slack, or an AI
  assistant.
- **If it leaks** (or someone leaves the team): Cloud Console → service account → *Keys* →
  delete the key → create a new one → update the password manager and the GitHub secret →
  everyone replaces `secrets/service-account.json`. Takes 5 minutes; do it without debate.
- **End of course:** delete the service account (or the whole project) and the test calendar.
- **The API itself has no authentication.** Run it on `127.0.0.1` only until the
  authentication issue in `docs/NEXT_STEPS.md` is done.

## 7. Access checklist (tick before assigning implementation work)

- [x] Cloud project exists; Calendar API enabled
- [ ] Service account created; key stored in `secrets/` by every developer; in the password manager
- [x] Test calendar created and shared with the robot ("Make changes to events")
- [ ] Every developer has run `uv run pytest -m integration` successfully
- [ ] GitHub secrets set; manual CI run shows the integration job green
- [ ] Branch protection on `main` enabled
- [ ] Roles in §0 filled in and copied to `docs/TEAM_AGREEMENT.md`
