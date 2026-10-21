# BASK'D: final release checklist (`v0.1.0`, due Wednesday October 21 before class)

Team 7 · Calendar · Google Calendar. This list combines spec Level 5, the spec's testing
section, the handout's release and submission sections, and the TA's instructions for the
final submission. **Owners are proposals: acknowledge or swap them in the team channel.**
The release procedure itself is `AGENTS.md` §5; this file does not override it.

Status: ✅ done · 🟡 done, waiting for review or merge · ⬜ not started

## 1. Product (Level 5) and review feedback

| Requirement | Status | Evidence | Owner |
| --- | --- | --- | --- |
| Documented, consistent error format; callers can tell invalid input, missing resource, access denial and provider failure apart; retry guidance | 🟡 | README [Errors](../README.md#errors); [#20](https://github.com/samthropic/BASKD/pull/20) | Arda |
| Provider failures translated before reaching the caller; no provider text in the contract | 🟡 | `providers/google.py::translate_http_error`; #20 | Arda |
| Failure tests through the controlled provider (success, invalid, missing, provider failure) | 🟡 | `tests/unit/test_failure_logging.py`; #20 | Arda |
| Sanitized structured failure logs with request ids | 🟡 | `api/failure_log.py`; #20 | Arda |
| One real provider failure verified | 🟡 | `test_calendar_the_service_cannot_see_is_an_access_denial`; #20 CI | Arda |
| Team agrees on error shape, names, statuses, what is logged and what is retryable (spec 5.7), including **502 rather than 403** for a provider access denial | ⬜ | Approve or comment on #20 | everyone |
| Team 6's review: every point fixed or answered (handout §3.2) | 🟡 | Fixes in [#19](https://github.com/samthropic/BASKD/pull/19) (closes #17); the reply on PR #1 still has to be posted | Arda |
| TA feedback ("more in-depth feedback later this week") answered with a fix or a reasoned reply | ⬜ | PR #1, once it arrives | whoever owns the area |
| One justified usability improvement from review feedback, explained in its PR (handout §3.2) | 🟡 | #19's cursor-scope change makes the README's "only valid with the same from/to" true | Arda |
| Reviews: #19, then #20, then this docs PR, each by someone who did not write it; provider changes get a second reviewer (`AGENTS.md` §3) | ⬜ | | Sam, Bryant, Karthik, Dan |

## 2. Required write-ups (link each from the final submission)

| Requirement | Status | Evidence | Owner |
| --- | --- | --- | --- |
| Testing strategy | 🟡 draft | [`TESTING.md`](../TESTING.md) | Karthik to review |
| One engineering decision: constraints, alternatives, evidence, tradeoffs, when to revisit | 🟡 draft | [`docs/DECISIONS.md`](DECISIONS.md) | Sam to review |
| One operation's cost: sizes, data structures, time/space, provider calls, local vs provider work | 🟡 draft | [`docs/COST.md`](COST.md) (`GET /events`) | Bryant to review |
| A test shown to detect a defect (spec Testing §1.5) | ✅ | #19 "How was this tested?" | Arda |
| A bug investigated with evidence (spec Testing §1.6) | ✅ | #19 "Bug investigation record" | Arda |
| Process observation after the review release, and one adjustment | 🟡 draft | `docs/TEAM_AGREEMENT.md` §7, `AGENTS.md` §5 | everyone accepts in review |
| Extend a teammate's feature through a normal PR, or explain why it could not be done (handout §6.3) | ⬜ | | one per person who did not lead the feature |
| **Demonstration** (video, GIF or `TUTORIAL.md` with screenshots) showing expected vs actual results of the workflow, **with every member taking part** | ⬜ | | Dan to coordinate; each owner demos their operation |

Suggested demo script (about 5 minutes, against Google, Swagger or `curl`): each owner states
the expected result, then shows the actual one. Sam creates, Arda reads, Bryant lists and
pages, Karthik replaces (including the refused all-day case), Dan deletes and repeats it.
Then one failure each: a 422 for a numeric timestamp, a 404, a cursor reused with another
window, and a log line with its `X-Request-ID`.

## 3. The release (`AGENTS.md` §5)

| Step | Status | Owner |
| --- | --- | --- |
| Coordinator named. **Must not be Arda**, who coordinated rc.1 | ⬜ | Dan or Sam |
| Merge #19 → #20 → this docs PR into `arda/milestone-1`, then PR #1 into `main` under branch protection | ⬜ | coordinator |
| Move `CHANGELOG.md` "Unreleased" into a dated `0.1.0` section | ⬜ | coordinator |
| CI green on the exact release commit, including the real-Google job | ⬜ | coordinator |
| Annotated tag `v0.1.0` on that commit and pushed; never move it, and never move `v0.1.0-rc.1` or `v0.1.0-alpha.1` | ⬜ | coordinator |
| Fresh-checkout verification of the tag by a different teammate, with their OS stated, linked on the draft **before** publishing (new rule, see `TEAM_AGREEMENT.md` §7) | ⬜ | not the coordinator |
| Publish the GitHub Release (not a prerelease) with notes, known limitations, CI and verification links | ⬜ | coordinator |
| Late rc.1 verification (still pending since Oct 14): do it, or say in the final notes that it was superseded by the `v0.1.0` verification | ⬜ | Karthik |

## 4. Submission and individual work

| Requirement | Owner |
| --- | --- |
| One team submission: final PR and final release link, tag and commit SHA; check all links work for staff | coordinator |
| Submission note: completed requirements with links, known gaps, changes made after review | coordinator, from this file |
| `docs/TEAM_AGREEMENT.md`: fill the `_TBD_` rows (availability, coordination roles, acceptance) | everyone |
| Team update before class (shipped, changed decisions, blockers, next steps) | rotating |
| Private individual reflection (not in the repository) | everyone |

## 5. Draft release notes for `v0.1.0` (the coordinator edits and fills the links)

```markdown
## v0.1.0: Final release (spec Level 5)

**Team 7 · BASK'D** · Calendar · Google Calendar · commit `<sha>`

### What's new since v0.1.0-rc.1
- **Level 5, consistent failure handling** (#18, #20):
  - one documented error table (code, status, kind, when, retry guidance);
  - provider failures translated into provider-neutral messages;
  - `X-Request-ID` on every response;
  - one sanitized JSON log line per failed request.
- **Team 6 review fixes** (#17, #19):
  - Windows time zones (`tzdata`);
  - numeric timestamps rejected;
  - whole-second list bounds;
  - cursors bound to their window.
- **Documentation:** testing strategy, cost of `GET /events`, an engineering decision record,
  and the release-process adjustment.

### Breaking changes
- A number or numeric string is no longer accepted as a timestamp (`422`).
- List cursors issued by v0.1.0-rc.1 are rejected (`400 invalid_request`); start the listing
  again without a cursor. A cursor now only works with the `from`/`to` it was issued for.
- Error *messages* changed wording (codes and statuses did not). Clients should branch on
  `code`.

### Setup changes
- `tzdata` is a new dependency; `uv sync --locked` installs it.

### Known limitations
- No attendees; all-day events and recurring series are read-only; no `PATCH`; one
  calendar per instance.
- No idempotency keys or automatic retries: a `POST` that timed out may have succeeded, so
  list before re-sending.
- Testing gaps are listed in `TESTING.md` ("Known gaps").

### Verification
- CI on this commit: <link>
- Fresh-checkout verification by <name> on <OS>: <link>
- Real-provider verification log: `docs/REQUIREMENTS.md`
```
