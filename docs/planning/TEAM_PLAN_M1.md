# BASKD Team Plan — Milestone 1

## Goal

For Milestone 1, the team will use the existing implementation in **Daniel's `dan` branch as the first working version**.

Each team member will take ownership of one major calendar operation and be responsible for understanding, maintaining, improving, testing, and documenting that part of the implementation.

Each person should be able to explain the code they own and make any changes needed before the Milestone 1 submission.

The backend will focus on **calendar integrations for agents**.

---

## Current Starting Point

The current `dan` branch already includes:

- Create Event
- List Events
- Get Event
- Replace Event
- Delete Event
- Tests for the five main operations
- A working backend structure

This implementation will serve as the team's **first working version**.

The goal now is to divide ownership clearly across the five team members and make sure the implementation is understandable, documented, tested, and ready to merge into `main`.

### Work Already Documented in `arda/milestone-1`

The GitHub comparison of `dan` against `arda/milestone-1` shows **four changed documentation files (59 additions, 54 deletions)** and no application-code changes in that diff. This means Arda's visible changes are largely milestone clarification, ownership planning, and evidence of real-provider setup/testing—not a new implementation of List Events.

- **`docs/REQUIREMENTS.md`:** Replaced earlier assumptions about milestone requirements with information from the course's posted specs, rewrote completion criteria, and proposed ownership. That proposed table names **Arda for Get Event** and **Karthik for Replace Event**; other operations were left unassigned in that document.
- **`docs/HUMAN_STEPS.md`:** Records **Arda as owner of the Google Cloud project and test calendar**. The checklist marks the Cloud project/Calendar API and shared test calendar as set up; other steps, including each developer running integration tests, repository secrets, and branch protection, remain unchecked.
- **`docs/NEXT_STEPS.md`:** Reprioritizes assigning operation owners and proving behavior against the real calendar.
- **`docs/TEAM_AGREEMENT.md`:** Includes Karthik's availability information from a merged change; this should not automatically be counted as Arda's own authored contribution.

**Real-provider evidence:** `docs/REQUIREMENTS.md` records an **October 6** integration run by Arda against Google Calendar with **four tests passing** and the demo steps succeeding (recorded commit `f5592e4`). This is documented evidence, not a new test run by the team today. The document still identifies a **second team member independently repeating the provider workflow** as unfinished.

**Ownership note:** Because Arda's branch proposes `GET /events/{id}` for Arda, the table below moves **Arda to Get Event** and proposes **Bryant for List Events**. These revised assignments should be confirmed by the whole team before finalizing the issues.

---

## Team Work Split

| Team Member | Main Ownership | Responsibilities |
|---|---|---|
| **Sam** | Create Event — `POST /events` | Own the Create Event implementation, understand the request/provider flow, make needed changes, maintain related tests, and update documentation |
| **Arda** | Get Event — `GET /events/{id}` + Real-provider setup | Own individual event retrieval, Google Calendar test setup, the integration evidence, related tests, and documentation |
| **Bryant** | List Events — `GET /events` | Own listing, filtering, ordering, pagination/cursors, related provider behavior, tests, and documentation |
| **Karthik** | Replace Event — `PUT /events/{id}` | Own event replacement/update behavior, provider logic, tests, and documentation |
| **Daniel** | Delete Event — `DELETE /events/{id}` + Integration | Own deletion behavior and help coordinate the existing first working version, integration, CI, and final end-to-end testing |

---

# Individual Responsibilities

## Sam — Create Event

### Endpoint

`POST /events`

### Responsibilities

- Understand the existing Create Event implementation
- Understand how the FastAPI route receives the request
- Understand the event request/input model
- Understand the provider `create_event` method
- Understand how the request is converted into a Google Calendar event
- Make changes or fixes if needed
- Maintain or improve Create Event tests
- Update related API documentation
- Be able to explain the full Create Event request flow

### Areas to Review

- Event title
- Start time
- End time
- Timezone handling
- Description
- Location
- Google Calendar request format
- HTTP response/status code
- Error handling

### Tests to Own

- Successful event creation
- Invalid event input
- Invalid start/end times
- Invalid timezone/input
- Optional description/location
- Correct returned event information

---

## Bryant — List Events

### Endpoint

`GET /events`

### Responsibilities

- Understand the existing List Events implementation
- Own the event listing behavior
- Understand the query parameters
- Understand the provider `list_events` method
- Understand the Google Calendar list request
- Make changes or fixes if needed
- Maintain or improve List Events tests
- Update related API documentation
- Be able to explain filtering and pagination behavior

### Areas to Review

- Start/end time filtering
- Event ordering
- Result limits
- Pagination
- Cursor handling
- Google Calendar query parameters
- Empty result behavior
- Error handling

### Tests to Own

- Normal event listing
- Time-window filtering
- Ordering
- Result limits
- Pagination
- Invalid cursor
- Invalid query parameters
- Empty event list

---

## Arda — Get Event + Google Calendar Integration Setup

In addition to owning Get Event, Arda has already documented the shared Google Cloud/test-calendar setup and a successful real-provider test run on `arda/milestone-1`. He should coordinate access **privately**, without committing or pasting credentials into issues or chats.

### Additional integration follow-up

- Keep the setup and run instructions accurate in `docs/HUMAN_STEPS.md` and related docs.
- Help a **second teammate** run the documented Google Calendar integration test and demo with the test account.
- Record the second tester's outcome in the milestone evidence and resolve any discovered configuration problems with that teammate.
- Confirm the remaining setup checklist items have owners; do not mark CI secrets, access, or branch protection complete without evidence.

### Endpoint

`GET /events/{id}`

### Responsibilities

- Understand the existing Get Event implementation
- Own individual event retrieval
- Understand the provider `get_event` method
- Understand Google Calendar event retrieval
- Make changes or fixes if needed
- Maintain or improve Get Event tests
- Update related API documentation
- Be able to explain missing-event and provider error behavior

### Areas to Review

- Event ID handling
- Missing events
- Deleted/cancelled events
- Provider failures
- HTTP responses/status codes

### Tests to Own

- Successful event retrieval
- Unknown event ID
- Deleted/cancelled event
- Provider failure
- Authentication/provider error where applicable

---

## Karthik — Replace Event

### Endpoint

`PUT /events/{id}`

### Responsibilities

- Understand the existing Replace Event implementation
- Own event replacement/update behavior
- Understand the provider `replace_event` method
- Understand the Google Calendar update logic
- Make changes or fixes if needed
- Maintain or improve Replace Event tests
- Update related API documentation
- Be able to explain how replacement differs from creation

### Areas to Review

- Replacement request handling
- Optional fields
- Clearing description/location
- Maintaining the same event ID
- Missing events
- Error handling

### Tests to Own

- Successful event replacement
- Event ID remains the same
- Clearing description
- Clearing location
- Invalid replacement input
- Unknown event ID

---

## Daniel — Delete Event + Integration

### Endpoint

`DELETE /events/{id}`

### Responsibilities

- Understand and own the existing Delete Event implementation
- Understand the provider `delete_event` method
- Understand Google Calendar deletion behavior
- Make changes or fixes if needed
- Maintain or improve Delete Event tests
- Update related API documentation
- Be able to explain deletion and repeated deletion behavior

### Areas to Review

- Successful deletion
- Missing events
- Repeated deletion
- Google Calendar `404` / `410` behavior
- Correct HTTP status code

### Tests to Own

- Successful deletion
- Unknown event ID
- Repeated deletion
- Deleted event can no longer be retrieved
- Deleting one event does not affect another event

### Additional Responsibilities

Because Daniel created the initial first working version, he will also help coordinate:

- Getting the working application implementation into `main` via a reviewed PR
- Coordinating CI/checks and integration conflicts with the rest of the team
- Pairing with Arda on the final CRUD demo / second-person provider verification
- Final end-to-end testing before submission

**Division of integration work:** Arda owns the documented Google Cloud/test-calendar setup and recorded provider-testing evidence; Daniel coordinates the initial implementation and overall merge/integration process. These responsibilities are shared, not substitutes for other team members' contributions.

Daniel should not be solely responsible for fixing every endpoint. Each endpoint owner is responsible for their own area.

---

# GitHub Workflow

## 1. Use the Existing First Working Version

Daniel's `dan` branch contains the current first working version.

Before individual cleanup or improvement work begins, the team should review both `dan` and `arda/milestone-1`, then bring their work into `main` through reviewed PR(s). Because Arda's branch contains changes relative to `dan`, decide whether to integrate the whole branch or keep the implementation and documentation changes as separate PRs; **do not blindly merge overlapping copies**. Confirm the branch differences and owners first.

After the baseline is on `main`, everyone should start from the latest version:

```bash
git fetch origin
git switch main
git pull origin main
```

---

## 2. Create Feature/Ownership Branches

Each person should create a branch for changes related to the area they own.

Example:

```bash
git switch -c sam/create-event
```

Suggested branches:

```text
sam/create-event
arda/list-events
bryant/get-event
karthik/replace-event
daniel/delete-event
```

These branches are for improvements, fixes, tests, and documentation related to each person's assigned operation.

---

## 3. Create GitHub Issues

Create one issue for each owned operation:

1. Create Event
2. List Events
3. Get Event
4. Replace Event
5. Delete Event

Each issue should include:

- Owner
- Endpoint
- Current behavior already implemented in the baseline
- Changes or improvements needed (if any)
- Tests owned by that person
- Documentation owned by that person
- Reviewer
- Dependencies or blockers

Additional project-wide issues can be created for:

- Integration testing
- CI/setup
- Documentation cleanup
- Provider configuration
- Milestone submission preparation

---

## 4. Work on the Assigned Area

Each person should:

1. Read and understand their assigned implementation
2. Trace the FastAPI route through the provider layer
3. Understand the related Google Calendar behavior
4. Run the existing tests
5. Identify any bugs, missing cases, or unclear behavior
6. Make needed changes
7. Add or improve meaningful tests
8. Update related documentation
9. Run the relevant tests again
10. Commit the work
11. Open a pull request into `main`

The goal is not to make unnecessary changes just to increase the amount of code. Each owner should make meaningful changes only when needed.

---

# Pull Requests

Each person's changes should go through a pull request into `main`.

```text
sam/create-event      → main
arda/list-events      → main
bryant/get-event      → main
karthik/replace-event → main
daniel/delete-event   → main
```

Each PR should explain:

- What operation the person owns
- What they reviewed
- What they changed
- What tests they ran or added
- What documentation they updated
- Any known limitations

If the original implementation was generated with an AI coding agent, the owner should still be able to explain and maintain the code in their area.

---

# Review Rotation

| PR Author | Reviewer |
|---|---|
| Daniel | Karthik |
| Sam | Daniel |
| Arda | Sam |
| Bryant | Arda |
| Karthik | Bryant |

The reviewer should:

- Read the implementation
- Understand the change
- Review the tests
- Run the relevant tests when possible
- Leave comments if something is unclear or incorrect
- Approve the PR when it is ready

---

# Final Integration

After all endpoint-owner PRs are merged into `main`:

1. Pull the latest `main`
2. Run the full test suite
3. Run linting/checks
4. Configure Google Calendar test credentials
5. Run the real-provider integration tests
6. Run the complete CRUD workflow

```text
Create
  ↓
Get
  ↓
List
  ↓
Replace
  ↓
Delete
```

7. Confirm documentation matches the actual implementation
8. Confirm CI passes
9. Test setup from a fresh checkout
10. Make sure every team member can explain their contribution
11. Make sure `main` contains the completed Milestone 1 first working version

---

# Before Class Checklist

## First Working Version

- [ ] Team reviews `dan` and `arda/milestone-1` as the existing starting branches
- [ ] Arda's documentation changes and Daniel's application baseline reconciled and merged into `main` through reviewed PR(s)
- [ ] All five calendar methods are present
- [ ] Existing tests run successfully on the selected integration branch / `main` (separate from Arda's reported test run)
- [ ] Everyone has an assigned area of ownership

## Individual Ownership

- [ ] Team confirms proposed ownership assignments (Arda: Get; Bryant: List)
- [ ] Sam owns Create Event
- [ ] Arda owns Get Event
- [ ] Bryant owns List Events
- [ ] Karthik owns Replace Event
- [ ] Daniel owns Delete Event
- [ ] Each person understands their implementation
- [ ] Each person owns the tests for their operation
- [ ] Each person updates related documentation
- [ ] Any needed fixes/improvements are submitted through PRs
- [ ] Each PR receives teammate review

## Team Integration

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Google Calendar integration works
- [ ] A second team member independently repeats Arda's documented Google Calendar integration test and demo
- [ ] Remaining credential/configuration, CI secrets, and branch protection steps are assigned and completed where required
- [ ] Create works
- [ ] Get works
- [ ] List works
- [ ] Replace works
- [ ] Delete works
- [ ] Full CRUD workflow works
- [ ] CI passes
- [ ] Setup instructions work from a fresh checkout
- [ ] Documentation is complete
- [ ] `main` contains the Milestone 1 first working version

---

# What Everyone Should Be Able to Explain

By class, every team member should be able to explain:

1. Which endpoint they own
2. How that endpoint works
3. Which files contain the relevant implementation
4. How the FastAPI route interacts with the provider
5. How the Google Calendar integration works
6. What errors or edge cases are handled
7. What tests cover the feature
8. What changes they personally made
9. How their feature connects to the rest of the backend

The goal is for the team to use the existing first working version while giving every team member clear ownership and responsibility for a meaningful part of the calendar service.
