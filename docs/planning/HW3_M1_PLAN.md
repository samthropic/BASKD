# BASK'D Team Plan: HW3 Milestone 1 (Compose the Services)

Draft by Arda, Nov 20, 2026. Owners are **proposed**: acknowledge or swap in the team channel
before you start. Nothing here overrides `AGENTS.md`.

Source: the HW3 handout, "OSPSD Fall '26 - HW3" (Student Portal → Homeworks), tabs
"Compose the Services" (§3) and "Write the Design Document" (§4), plus the Brightspace
assignment "Homework 3 - Milestone 1".

## 1. Where we stand

- **Due date.** Milestone 1 was due **Wed Nov 18, 6:30 PM**. We have no HW3 work in the repo.
  - Arda asked Hari (Nov 20) whether we can still submit late. The handout says slack days
    must be requested before the deadline; any other extension is up to course staff.
  - **We need to agree on a submission date today** so Arda can give Hari a realistic one.
    Proposed: **Mon Nov 23, before 6:30 PM**.
- **Milestone 2 is due Dec 2.** It covers the product brief, the interface, the LLM agent
  service, sign-in and production readiness. Launch week starts Dec 2 for every team whether
  or not we're ready. Milestone 1 cannot take more than this weekend.
- **What we already have:**
  - Our calendar behind the shared contract: `baskd.contract.ContractCalendarService`
    implements `calendar_contract.CalendarService`, tested by the shared conformance suite.
  - An HW1 error model with `code`, `message` and `retryable` (`src/baskd/errors.py`,
    `src/baskd/api/errors.py`).
  - Configuration-based provider choice (`src/baskd/settings.py`,
    `src/baskd/providers/__init__.py::build_provider`).
  - The HW2 pipeline: tag → `deploy.yml` → Cloud Run by digest → smoke check → promote, with
    configuration from Terraform and Secret Manager.
  - The HW2 consumer workflow (create → get → replace → delete) exists only as a snippet in
    `DESIGN.md` §8. It was never committed or run against the deployed service.
- **Examples to learn from:**
  - **Team 2's full Milestone 1**, PR Airbus-A330/OSPSD-Team-2#89. Their docs admit they did
    no real swap.
  - **Team 4's product** (`Tyler-Arciniaga/OSPSD-Team-4`, `product/`). It did a real storage
    swap from Team 3 to Team 1 on Python 3.14. See
    `product/docs/evidence/storage-swap.md`.

## 2. What Milestone 1 requires (handout §3–4)

The API service must:

1. be written in Python and depend on **tagged** revisions of the HW2 shared contract packages;
2. use **our** calendar implementation and **another team's** implementation for storage and
   for the issue tracker;
3. select each implementation **through configuration**, so switching teams needs no code change;
4. expose **one operation** that completes a key scenario across all three verticals, with
   fixed steps and no language model;
5. translate a failure in any vertical into our **HW1 error model** and say **which step failed**;
6. **deploy through our HW2 pipeline**;
7. run with **one test account**, with credentials supplied from outside the repository.

**Verification:**
- Run the scenario on the deployed service and confirm the records in each provider.
- Switch one vertical to another team's implementation through configuration and run it again.
- Make one vertical fail through a controlled implementation and show the caller gets our
  documented error naming the failed step.

**DESIGN.md** (handout §4) must cover:
- An architecture diagram: caller, our API, the three verticals, where test credentials live.
- A traced request.
- The 2–3 decisions that matter most, each with its constraint, a credible alternative, the
  tradeoff and a condition for revisiting it.
- The boundaries: where inputs are validated, how implementations are selected, how
  credentials stay out of the repo.
- What could go wrong, including the partial-failure retry case: "if an event is created but
  saving its summary fails, what happens when the caller retries?"
- How we verify, separating controlled checks from real-provider checks.
- A review by another team, with the comments and our responses recorded.

**Submit on Brightspace** (one person, naming the team and all members):
- The deployed endpoint and usage instructions.
- The matching commit.
- Evidence for the composed workflow, the swap and the failure handling.
- DESIGN.md with the review comments and our responses.

**Not needed yet:** a language model, an interface, more than one user, or more than one
scenario.

## 3. Proposed workflow: meeting prep

`POST /workflows/meeting-prep`. Each step uses the previous step's result:

| # | Vertical (implementation) | Step | Contract call |
| --- | --- | --- | --- |
| 1 | Calendar (**ours**, `ContractCalendarService` on Google) | Create the meeting event | `CalendarService.create(CreateEvent)` → `event.id` |
| 2 | Cloud storage (**Team 3**, Dropbox; swap to **Team 1**) | Save an agenda at `/baskd/meeting-prep/<event.id>.md` with the event details and agenda | `DocumentStorage.create(path, bytes)` → `FileInfo` |
| 3 | Issue tracker (**Team 4**, Trello) | Create the issue `Prep: <title> [evt:<event.id>]` | `IssueProvider.create_issue(title)` → `Issue` |

**Why this workflow:**
- It is the handout's own partial-failure example (an event is created, then saving its
  summary fails).
- It touches every vertical with one write each.
- It fits the example products for Milestone 2 (standup, onboarding, sprint agents).

**The contracts shape it.** A shared `Issue` has only `id` and `title`, so the title carries
the event id. The agenda file is where the links live. If we want the file to include the
issue id, a fourth step would rewrite it with `DocumentStorage.replace`. Decide this in
DESIGN.md.

**Steps that will need judgment later** (handout question 4): writing the agenda, choosing
the time, and how the issue is worded and split. Fixed steps never need it: the order, the
naming, and linking the three records.

**Request:**

```json
{
  "title": "Design review: HW3",
  "start": "2026-11-24T15:00:00Z",
  "end": "2026-11-24T15:30:00Z",
  "agenda": "1. Walk through DESIGN.md\n2. Open questions"
}
```

**`201` response:**

```json
{
  "event": {"id": "..."},
  "document": {"path": "/baskd/meeting-prep/<event.id>.md"},
  "issue": {"id": "..."},
  "steps": ["create_event", "save_agenda", "create_issue"]
}
```

**Failure response.** Same envelope as HW1, plus two fields:

```json
{
  "error": {
    "code": "provider_unavailable",
    "message": "...",
    "retryable": true,
    "failed_step": "save_agenda",
    "completed": [{"step": "create_event", "id": "..."}]
  }
}
```

- The HTTP status is the failed step's error status under our HW1 mapping.
- `code` and `retryable` come from that step's error.
- `failed_step` and `completed` are new. **Adding fields to the error body is a documented
  extension; announce it in the changelog.**

**Mapping the other teams' errors to our five codes:**
- **Storage** errors are classes with fixed statuses (400, 403, 404, 409, 413, 422, 502, 503).
- **Tracker** errors are one `ServiceError` with a `code` and a `may_have_applied` flag.
- **Our rule:** anything that may have applied is `provider_error`, `retryable: false`. This
  is the same rule as HW2.

**Retries without duplicates.** This is the decision to settle in DESIGN.md. Proposal:

- **No rollback, no hidden retries.** We never delete what earlier steps created and never
  retry a write on our own. Turn off the Dropbox SDK's built-in retries, as Team 2 did with
  `sdk.clone(max_retries_on_error=0, max_retries_on_rate_limit=0)`.
- **The caller resumes instead of starting over.** The request accepts an optional
  `event_id`. When it is supplied, step 1 becomes a `get` instead of a `create`. So "event
  created, agenda failed" is retried with `event_id`, and no second event is created.
- **The agenda step is safe to repeat.** The path is derived from the event id, and the
  storage contract's `create` raises `ConflictError` instead of overwriting. On a conflict we
  read `get_metadata(path)` and treat the step as already done.
- **The issue step cannot be made safe through the contract.** It has no idempotent create.
  Team 4's `create_tagged_issue` exists, but only in their Trello package.
  - Before creating, we look for a recent issue whose title contains `[evt:<event.id>]`
    using `list_issues(limit=…)`. This is best-effort; document the limit.
  - If the create fails with `may_have_applied`, we report `retryable: false` and tell the
    caller to check the tracker.
  - Raise the missing idempotent create with Team 4 (see #70).

## 4. The other teams' packages

From a survey of the repos on Nov 20. Run `uv lock` before trusting any of it.

| Vertical | Team and implementation | Contract | Pin in our `pyproject.toml` | Credentials (env vars) |
| --- | --- | --- | --- | --- |
| Calendar | **7 (ours)**, `ContractCalendarService` | `calendar-contract` `v0.1.0-rc.1` | already there | `BASKD_GOOGLE_*` (unchanged) |
| Storage (primary) | **3**: `dropbox-client-impl` (`DropboxDocumentStorage`), Dropbox | Team 1's `cloud-storage-api`, tag `0.3.1` | `Shreyas191/OSPSD-Team-3`, tag `v0.3.0`, subdirs `src/dropbox_client_impl` **and** `src/cloud_storage_client_api` | `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` |
| Storage (swap) | **1**: `team1-dropbox-storage` (`Team1DropboxStorage.from_env()`), Dropbox | same | `Dayana20/sandbox`, **commit** `784be97fc111338c6746b9d7288bf84a333a9b16` (no tag yet; their issue #50 asks for one), subdir `packages/team1_dropbox` | the same three `DROPBOX_*` |
| Storage (not now) | **6**: `storage-service` (`document_storage_from_env()`), S3 | same | no usable tag; the adapter is only on branch `dev`, and `main` needs Python ≥ 3.13 | `S3_*` |
| Issue tracker | **4**: `team-4-issue-tracker-trello` (`TrelloIssueProvider()`), Trello. **Only Team 4 is in this vertical, so there's nothing to swap to.** | `issue-tracker-contract`, rev `issue-tracker-contract-v1.1.0` (subdir `contract`) | `Tyler-Arciniaga/OSPSD-Team-4.git`, rev `team-4-issue-tracker-trello-v1.0.0`, subdir `team-4-trello-impl` | `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_LIST_ID` |

**Consequences:**
- **The swap demo is on storage: Team 3 → Team 1.** Both use Dropbox with the same three
  credentials, so the swap really is a single config change.
- **Every package allows Python 3.12 and 3.14.** Team 6's `dev` branch is the exception
  noted above.

**Packaging traps others already hit:**
- **Pin Team 4's packages with `rev =`, not `tag =`.** Otherwise uv reports conflicting URLs.
- **Team 1 and Team 3 together** produce a "conflicting URLs" error for `cloud-storage-api`.
  Team 4's fix is to put
  `"cloud-storage-api @ git+https://github.com/Dayana20/ospsd26-cloud-storage.git@0.3.1#subdirectory=src/cloud_storage_api"`
  in `dependencies`, with no `[tool.uv.sources]` entry for it.
- **Team 1 pins `dropbox==12.1.0` exactly.**
- **`cloud-storage-api` reports version 0.2.0 at tag 0.3.1.** Pin it by tag, never by version.
- **Team 3's package calls `load_dotenv()` when imported,** and `register()` replaces a
  global. Keep test-account values out of any `.env` the tests read.
- **Trello reads its three variables on every call.** A missing one fails on first use with
  `service_not_configured`, not at startup. Our `Settings` must check them at startup.

## 5. Where the code goes (keeps the `AGENTS.md` §7 rule)

```
src/baskd/workflow/
  meeting_prep.py   # the fixed steps; imports only calendar_contract, cloud_storage_api, issue_tracker_contract
  composition.py    # the ONLY module that imports other teams' implementations; picks them from Settings
  controlled.py     # in-memory and always-failing DocumentStorage / IssueProvider for tests and the failure demo
src/baskd/api/workflows.py   # POST /workflows/meeting-prep, error translation, failed_step/completed
src/baskd/app.py             # wires the workflow from composition.build_workflow(settings)
src/baskd/settings.py        # selectors + fail-fast checks for the credentials of the chosen implementations
```

- `api/` knows only the workflow and the contract protocols, never a concrete team's package.
  This is the same dependency rule we keep for the Google SDK.
- Update the `AGENTS.md` §6 map with a new row: "Add or swap a vertical implementation".
- Update the README configuration table and `.env.example`.

**Configuration (proposed):**

| Variable | Values |
| --- | --- |
| `BASKD_PROVIDER` | `google` / `memory` (unchanged; our calendar) |
| `BASKD_WORKFLOW_STORAGE` | `team3` / `team1` / `memory` / `failing` |
| `BASKD_WORKFLOW_ISSUES` | `team4` / `memory` / `failing` |

- `failing` exists so the failure demo is a configuration change.
- Credentials keep the packages' own variable names (§4). They come from Secret Manager in
  Cloud Run and a local `.env` in development, and are never committed.

**Alternative to weigh in DESIGN.md:** Team 4 selects implementations with a `module:attr`
string per vertical and checks the result with `isinstance`. It is more flexible, but the
config can then import any code. A fixed list of names keeps the dependency rule visible.

## 6. Issues (opened Nov 20)

Sizes follow `AGENTS.md` §1: S ≤ 2 h, M ≤ 1 day. Owners are proposals.

| # | Title | Size | Owner (proposed) | Depends on |
| --- | --- | --- | --- | --- |
| [#62](https://github.com/samthropic/BASKD/issues/62) | Set up the HW3 test accounts: Dropbox app and Trello board | S | Arda | – |
| [#63](https://github.com/samthropic/BASKD/issues/63) | Write the DESIGN.md "HW3 composition" section | M | Arda | – |
| [#64](https://github.com/samthropic/BASKD/issues/64) | Add the storage and issue-tracker packages and select implementations by config | M | Karthik | – |
| [#65](https://github.com/samthropic/BASKD/issues/65) | Controlled storage and tracker implementations for tests and the failure demo | S | Bryant | #64 |
| [#66](https://github.com/samthropic/BASKD/issues/66) | Add `POST /workflows/meeting-prep` with step-level failure reporting | M | Sam | #64, #65 |
| [#67](https://github.com/samthropic/BASKD/issues/67) | Deploy the workflow through the HW2 pipeline | M | Arda + Daniel | #62, #66 |
| [#68](https://github.com/samthropic/BASKD/issues/68) | Collect verification evidence: real run, storage swap, controlled failure | S | Daniel | #67 |
| [#69](https://github.com/samthropic/BASKD/issues/69) | Get an outside design review and record our responses | S | Arda | #63 |
| [#70](https://github.com/samthropic/BASKD/issues/70) | Report contract mismatches to the owning teams | S | whoever finds one | – |
| [#71](https://github.com/samthropic/BASKD/issues/71) | Tag, deploy and submit HW3 Milestone 1 | S | Release coordinator (a different teammate from the last release's) | all |

Done criteria are in each issue.

**Running alongside:**
- PR #61 and the `v0.2.1` release for Team 3.
- Team updates: Oct 28 and Nov 18 were missed. Nov 25 is due 2 h before class.

## 7. Schedule (if Hari accepts Mon Nov 23)

| Day | Goal |
| --- | --- |
| Fri Nov 20 | Agree on workflow, owners and date; tell Hari; test accounts (#62); ask Team 3 for the design review (#69) |
| Sat Nov 21 | DESIGN.md draft out for review (#63); packages and config merged (#64); controlled implementations (#65) |
| Sun Nov 22 | Endpoint and tests merged (#66); secrets and staging deploy (#67); answer review comments (#69) |
| Mon Nov 23 | Real-provider run, swap, failure evidence (#68); tag, deploy, submit (#71) |

## 8. Open questions for the team

1. Is "meeting prep" the right workflow, or do we already have a Milestone 2 product in mind
   that the workflow should match?
2. Who does the design review? Team 3 is the natural partner: we depend on their storage and
   they depend on our calendar. Teams 2 and 5 also offered exchanges on Nov 18.
3. Course staff need to call a private Cloud Run service. Do we add their accounts as
   invokers (they then call it with `gcloud auth print-identity-token`), or add a simple
   API key now? Milestone 2 brings real sign-in anyway.
4. Who owns the Dropbox app and the Trello board? Whoever creates them can revoke them. Use
   throwaway test accounts, as we did with the test calendar.
