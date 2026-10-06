# BASKD Team Plan — Milestone 1

## Goal

Daniel will first move the **basic shared project scaffold** onto `main`. Once that shared foundation is available, each team member will create a feature branch from `main` and implement their assigned calendar operation.

Each person is responsible for:

- Understanding what their endpoint is supposed to do
- Creating the endpoint implementation
- Creating the provider logic for that operation
- Creating the Google Calendar integration for that operation
- Creating validation and error handling
- Creating tests for their feature
- Updating related documentation
- Opening a pull request into `main`
- Being able to explain the code they created

The backend will focus on **calendar integrations for agents**.

---

## Team Work Split

| Team Member | Main Ownership | Responsibilities |
|---|---|---|
| **Sam** | Create Event — `POST /events` | Create event endpoint, input models, validation, Google Calendar create logic, tests, and documentation |
| **Arda** | List Events — `GET /events` | Create list endpoint, filtering, time windows, ordering, pagination, Google Calendar list logic, tests, and documentation |
| **Bryant** | Get Event — `GET /events/{id}` | Create get endpoint, missing-event handling, provider errors, Google Calendar get logic, tests, and documentation |
| **Karthik** | Replace Event — `PUT /events/{id}` | Create replace endpoint, update logic, validation, Google Calendar update logic, tests, and documentation |
| **Daniel** | Delete Event + Project Scaffold | Create delete endpoint and create the basic shared project scaffold on `main` |

---

# Shared Project Scaffold

Before everyone starts their individual features, Daniel will create and commit the **basic project scaffold to `main`**.

The scaffold should include the shared foundation that everyone needs to build their feature.

## Daniel — Scaffold Responsibilities

Create and commit:

- Base project folder structure
- FastAPI application setup
- Shared configuration files
- Dependency setup
- Shared calendar models/interfaces
- Provider abstraction/interface
- Google Calendar client/configuration setup
- Test folder and basic test configuration
- Basic CI/check configuration
- Documentation folders
- `.gitignore`
- Environment variable template/setup instructions
- Shared starter code needed by multiple endpoints

The scaffold should **not include completed implementations of the other team members' assigned endpoints**.

Once the scaffold is merged into `main`, everyone should branch from `main`.

---

# What We Need to Create

Across the project, the team needs to create:

- FastAPI routes for each calendar operation
- Request and response models
- Input validation
- Calendar provider interface methods
- Google Calendar provider implementations
- HTTP status codes
- Error handling
- Missing-resource behavior
- Date/time and timezone handling
- Pagination where applicable
- Unit tests
- Integration tests
- API documentation
- Setup documentation
- Real Google Calendar integration
- End-to-end CRUD workflow
- CI/test commands
- Fresh-checkout setup instructions

Each person's feature should include:

> **Endpoint + Provider Logic + Google Calendar Integration + Validation + Error Handling + Tests + Documentation**

---

# Individual Tasks

## Sam — Create Event

### Endpoint

`POST /events`

### Create

- FastAPI route for creating an event
- Event request/input model
- Event response model if needed
- Title validation
- Start/end time validation
- Timezone handling
- Description/location handling
- Calendar provider `create_event` method
- Google Calendar event creation logic
- Conversion from our event model to the Google Calendar request body
- Correct HTTP response/status code
- Unit tests
- Integration test support
- API documentation

### Tests to Create

- Successful event creation
- Invalid title
- Invalid start/end times
- Invalid timezone/input
- Unknown or extra fields
- Correct returned event information

### Suggested Branch

```bash
sam/create-event
```

---

## Arda — List Events

### Endpoint

`GET /events`

### Create

- FastAPI route for listing events
- Query parameters
- Start/end time filtering
- Event ordering
- Result limit handling
- Pagination
- Cursor handling
- Calendar provider `list_events` method
- Google Calendar list logic
- Google Calendar query parameters
- Overlapping-event behavior
- Error handling
- Unit tests
- Integration test support
- API documentation

### Tests to Create

- Normal event listing
- Time-window filtering
- Correct ordering
- Result limits
- Pagination
- Invalid cursor
- Invalid query parameters
- Empty event list

### Suggested Branch

```bash
arda/list-events
```

---

## Bryant — Get Event

### Endpoint

`GET /events/{id}`

### Create

- FastAPI route for fetching one event
- Event ID handling
- Calendar provider `get_event` method
- Google Calendar event retrieval
- Missing event handling
- Deleted/cancelled event handling
- Provider error handling
- API error responses
- Correct HTTP status codes
- Unit tests
- Integration test support
- API documentation

### Tests to Create

- Successful event retrieval
- Unknown event ID
- Deleted/cancelled event
- Provider failure
- Authentication/provider error where applicable

### Suggested Branch

```bash
bryant/get-event
```

---

## Karthik — Replace Event

### Endpoint

`PUT /events/{id}`

### Create

- FastAPI route for replacing an event
- Replacement request model
- Input validation
- Calendar provider `replace_event` method
- Google Calendar update logic
- Handling for optional fields
- Clearing description/location when removed
- Maintaining the same event ID
- Missing event handling
- Error handling
- Unit tests
- Integration test support
- API documentation

### Tests to Create

- Successful event replacement
- Event ID remains the same
- Clearing description
- Clearing location
- Invalid replacement input
- Unknown event ID

### Suggested Branch

```bash
karthik/replace-event
```

---

## Daniel — Delete Event

### Endpoint

`DELETE /events/{id}`

### Create

- FastAPI route for deleting an event
- Calendar provider `delete_event` method
- Google Calendar deletion logic
- Missing event handling
- Repeated delete handling
- Correct HTTP status code
- Google Calendar `404` / `410` handling
- Unit tests
- Integration test support
- API documentation

### Tests to Create

- Successful deletion
- Unknown event ID
- Repeated deletion
- Deleted event can no longer be fetched
- Deleting one event does not affect another event

### Additional Responsibilities

Daniel will also handle:

- Basic shared project scaffold
- Google Calendar configuration setup
- Integration test configuration
- CI setup/checks
- Full CRUD integration after all feature PRs are merged
- Final end-to-end testing

### Suggested Branch

```bash
daniel/delete-event
```

---

# GitHub Workflow

## 1. Daniel Creates the Scaffold

Daniel creates the basic shared project scaffold and opens a PR into `main`.

Once the scaffold is merged, everyone starts from the updated `main`.

```bash
git fetch origin
git switch main
git pull origin main
```

---

## 2. Create Your Feature Branch

Each person creates their own branch from `main`.

Example:

```bash
git switch -c sam/create-event
```

Other branches:

```text
sam/create-event
arda/list-events
bryant/get-event
karthik/replace-event
daniel/delete-event
```

---

## 3. Create GitHub Issues

Create one GitHub Issue for each feature:

1. Create Event
2. List Events
3. Get Event
4. Replace Event
5. Delete Event

Each issue should include:

- Owner
- Endpoint
- Deliverables
- Tests to create
- Documentation to create
- Reviewer
- Dependencies/blockers

---

## 4. Build Your Assigned Feature

Each person should:

1. Understand the contract for their endpoint
2. Create the FastAPI route
3. Create request/response models
4. Create the provider/interface method
5. Create the Google Calendar implementation
6. Create validation
7. Create error handling
8. Create unit tests
9. Add integration test support
10. Update documentation
11. Run their tests
12. Commit their work
13. Open a pull request into `main`

---

# Commit Examples

Feature implementation:

```text
feat: implement create event endpoint
```

Tests:

```text
test: add create event validation tests
```

Pagination:

```text
feat: implement event list pagination
```

Error handling:

```text
fix: handle missing calendar events
```

Documentation:

```text
docs: document replace event endpoint
```

---

# Pull Requests

Each person should open a PR from their feature branch directly into `main`.

```text
sam/create-event      → main
arda/list-events      → main
bryant/get-event      → main
karthik/replace-event → main
daniel/delete-event   → main
```

Each PR should explain:

- What endpoint was created
- What files were added or changed
- How the endpoint works
- What validation/error handling was created
- What tests were created
- Any known limitations

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
- Understand how the endpoint works
- Read the tests
- Run the relevant tests when possible
- Leave comments if changes are needed
- Approve the PR when it is ready to merge

---

# Final Integration

After all five feature PRs are merged into `main`:

1. Pull the latest `main`
2. Run the full test suite
3. Run linting/checks
4. Configure Google Calendar test credentials
5. Run integration tests
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

7. Make sure documentation is complete
8. Make sure CI passes
9. Test setup from a fresh checkout
10. Make sure `main` contains the completed Milestone 1 implementation

---

# Before Deadline Checklist

## Scaffold

- [ ] Daniel created the basic project scaffold
- [ ] Scaffold PR merged into `main`
- [ ] Everyone pulled the updated `main`

## Individual Work

- [ ] Sam created Create Event
- [ ] Arda created List Events
- [ ] Bryant created Get Event
- [ ] Karthik created Replace Event
- [ ] Daniel created Delete Event
- [ ] Each person created tests for their feature
- [ ] Each person updated documentation for their feature
- [ ] Each person opened a PR
- [ ] Each PR received a teammate review

## Team Integration

- [ ] All five feature PRs merged into `main`
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Google Calendar integration works
- [ ] Create works
- [ ] Get works
- [ ] List works
- [ ] Replace works
- [ ] Delete works
- [ ] CI passes
- [ ] Setup instructions work from a fresh checkout
- [ ] Documentation is complete
- [ ] `main` contains the completed Milestone 1 implementation

---

# What Everyone Should Be Able to Explain

By class, every team member should be able to explain:

1. What endpoint they created
2. What files they worked on
3. How their FastAPI route works
4. How their provider method works
5. How their Google Calendar integration works
6. What validation they created
7. What errors their endpoint handles
8. What tests they created
9. How their feature connects to the rest of the backend

The goal is for every team member to have clear ownership over a meaningful part of the calendar service while still understanding how all five operations work together.