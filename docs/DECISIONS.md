# Engineering decision: a Google service account bound to one shared calendar

_Drafted for Sam Fiallos to review, correct and sign off (spec §6.1: justify one
substantial decision). Shorter decisions are in [`REQUIREMENTS.md`](REQUIREMENTS.md) §2._

**Decision.** BASK'D authenticates to Google Calendar as a *service account* (a robot
identity with a JSON key), and each running instance is bound to exactly **one** calendar,
named in configuration (`BASKD_GOOGLE_CALENDAR_ID`) and shared with that robot. Callers
never authenticate to Google and never choose a calendar.

## The problem and the constraints that mattered

We needed a real provider integration that every one of five teammates, CI, and a sister
team could run from a fresh checkout, with:

- **No interactive step.** Tests and CI must authenticate unattended.
- **Low setup cost.** The handout asks that access be verified before work is divided, and
  that a new developer can set up from the docs alone.
- **A disposable test calendar** "containing data your team may change", never anyone's
  personal calendar.
- **No cost**, and nothing that needs an administrator we do not have (we have personal
  Google accounts, not a Workspace domain).

## Alternatives considered

| Option | What it would have taken | Why not |
| --- | --- | --- |
| **User OAuth** ("Desktop app" client, browser consent, stored refresh token) | A consent screen, a one-time browser flow per developer, refresh tokens stored and refreshed, an unverified-app warning | Interactive: CI cannot click "Allow". Each developer would hold a token to their *own* account, which defeats a shared disposable calendar |
| **Service account with domain-wide delegation** (impersonating users) | A Google Workspace admin granting the robot scopes for a whole domain | We have no Workspace domain or admin; far more privilege than a test calendar needs |
| **Another provider** (Microsoft Graph, Cal.com, CalDAV) | Azure app registration and admin consent; or a bookings model rather than calendar events; or an old protocol with weak Python libraries | More setup or a worse fit for create/read/list/replace/delete of events |
| **Calendar id in the URL** (`/calendars/{id}/events`) instead of one configured calendar | A path parameter and an allow-list | Lets a caller reach any calendar the robot can see; nothing in the spec needed more than one |

## Evidence

Observations (things we did or saw):

- Setup took one sitting on Oct 6: Cloud project, Calendar API, service account, key, test
  calendar shared with the robot ([`HUMAN_STEPS.md`](HUMAN_STEPS.md)). The real-Google tests
  passed the same day.
- Three members verified the integration independently by Oct 7 with the shared key and
  calendar id, with no per-person Google setup (verification log in
  [`REQUIREMENTS.md`](REQUIREMENTS.md) §1).
- CI runs the same integration tests unattended from two repository secrets.
- Binding to one calendar made a misconfiguration observable: a calendar the robot cannot
  see answers 404, which we report as `502 access_denied`. The integration test
  `test_calendar_the_service_cannot_see_is_an_access_denial` shows this against Google.

Assumptions (taken from Google's documentation, not observed by us):

- A service account cannot invite attendees without domain-wide delegation
  (`forbiddenForServiceAccounts`). We never tried, because the API exposes no attendees.
- Access tokens last about an hour and are refreshed automatically by `google-auth`.

## What we gave up

- **Attendees.** The API has no attendee field rather than one that would fail.
- **Acting as a user.** Events are created by the robot, in a calendar shared with it, not
  in the caller's own calendar. An agent cannot manage *your* calendar through this service.
- **More than one calendar** per running instance.
- **A shared secret.** One key serves the whole team and CI. It has to be passed privately
  between people, and anyone holding it can write to the test calendar. The blast radius is
  that one calendar, and the rotation steps are in `HUMAN_STEPS.md` §6, but it is a manual
  process that relies on people.

## What remains uncertain

- Whether service-account quotas differ from user quotas under heavier use. We never came
  close to any limit.
- How Google treats a page token presented with different parameters. We no longer depend
  on it: since #19 the API rejects a cursor used with another window before Google sees it.

## When we would revisit it

- The service has to act on **users' own calendars**, for example an agent managing a
  person's schedule. That needs user OAuth (or delegation in a Workspace domain), and
  per-user credentials become part of the API.
- **Attendees or invitations** become a requirement.
- Callers need **several calendars**: add a path parameter guarded by an allow-list in
  settings, keeping the one-calendar default.
- The key leaks, or the team grows enough that sharing one key is unmanageable: move CI to
  workload identity federation and give each developer their own key or calendar.
