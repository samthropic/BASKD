# Next steps

A prioritised backlog for after Milestone 1. Turn each item into a GitHub Issue with an owner,
size and reviewer (AGENTS.md §1) before anyone starts on it; this file is the shared memory of
*why* each item exists, not the tracker.

## P0: before Milestone 1 is declared done (Oct 7)

1. **Assign operation owners** (`docs/REQUIREMENTS.md` §1): one operation per member, as the
   spec requires. Post remaining open questions (REQUIREMENTS §4) on `#help`.
2. **Run the slice against the real calendar** (docs/HUMAN_STEPS.md §1-§3) and attach the
   output of `uv run pytest -m integration -ra` and `make demo` to the milestone issue. Until
   this happens, the Google provider is verified only by offline tests with fake SDK responses.
3. **Set GitHub secrets and branch protection** (HUMAN_STEPS §4-§5) so CI proves the above on
   every merge.
4. **Fill in `docs/TEAM_AGREEMENT.md`** and have everyone accept it in a PR review.
5. **Repository polish that only a GitHub admin can do:** set the repository description and
   topics (`fastapi`, `google-calendar`, `python`), enable Issues and create the Projects board
   with the columns named in `AGENTS.md` §1, and enable Discussions or pin the milestone issue.
6. **Open the first issues from this list and from any staff answers**; tag the milestone
   commit `v0.1.0-alpha.1` once a teammate has verified a fresh checkout (AGENTS.md §5).

## P1: the next levels (likely Level 3/4, "repeated requests" and "provider failures")

6. **Idempotent create.** Accept an `Idempotency-Key` header (or a client-supplied `id`).
   Google supports client-chosen event ids on `events.insert` and answers 409 on duplicates,
   which maps naturally to "return the existing event". The fake needs a key → id table.
   Needed before any automatic retry of `POST`.
7. **Retries with backoff for idempotent calls** (GET/list/DELETE, and POST once #6 exists),
   with a per-request deadline; keep returning `503 + Retry-After` when the budget is spent.
   Add a unit test that counts attempts against the fake SDK.
8. **Circuit breaker / fast-fail** when Google has been failing for N seconds, so a provider
   outage does not tie up the thread pool. Expose state on `/health` as `"provider_status"`.
9. **Structured request logging and metrics** (request id, provider latency, error codes) so
   provider failures are diagnosable. Keep the logging policy: never log event content.
10. **`PATCH /events/{id}`** with merge semantics (move an event by sending only `start`/`end`).
    Design decision recorded in ARCHITECTURE §3: validate the merged result once, in a thin
    service layer between handlers and providers; that layer also hosts #6-#8.

## P2: functionality the real calendar has and we do not expose

11. **All-day events** on create/replace (`all_day: true` with date-only bounds).
12. **Recurring events** (RRULE) create/read; decide whether instances or series are the unit.
13. **Attendees.** Blocked by the service-account limitation; options are domain-wide
    delegation (needs a Workspace admin) or a user OAuth flow. Needs a staff/team decision.
14. **Multiple calendars** (`/calendars/{id}/events`), gated by an allow-list in settings.
15. **Free/busy and conflict detection** (`GET /availability?from&to`), a natural "collection"
    feature that composes existing list semantics.

## P3: hardening and operations

16. **Caller authentication** (API key header or OAuth bearer tokens) and rate limiting. The
    service must not be exposed beyond localhost before this lands.
17. **Deployment** to Cloud Run (or similar) following `docs/DEPLOYMENT.md`, with the deploy
    step wired to tagged releases.
18. **Slimmer image** (currently ~450 MB; `uvicorn[standard]` extras and the discovery
    documents bundled with the Google SDK dominate) and a `docker compose` file for local
    runs with a `.env`.
19. **Contract tests** that run the *same* behavioural test suite against both providers (a
    parametrised fixture), so the fake can never silently drift from Google.
20. **Dependabot / Renovate** for `uv.lock` and the SHA-pinned GitHub Actions.

## Extension idea on the table: an email-reading agent

The team floated a messaging/agent feature that checks, reads and drafts replies to email.
Recommendation: **not for Milestones 1-2.** Reasons, in order:

- It is a second provider integration (Gmail) with a different data model, plus an LLM
  dependency, plus the hardest security problem in the project (acting on someone's mailbox).
  The handout asks for one category done thoroughly; graders will look at depth first.
- It is unclear whether it counts toward the calendar category or extra credit (open question
  #4 in REQUIREMENTS). Get an answer before investing.
- The prerequisites it needs are exactly P1/P3 above: idempotency (never send twice),
  retries with a deadline, caller authentication, and a logging policy for sensitive content.

If staff confirm it is welcome, the smallest credible version that reuses our architecture:
a `MailProvider` port with a Gmail implementation and a fake, read-only first
(`GET /mail/threads?since=`), then "draft a reply" that **creates a draft** rather than
sending, then optionally "find a time" that calls our own calendar list endpoint. Sending
mail on a user's behalf would stay out of scope for the course.
