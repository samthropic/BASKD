# Team agreement

**Status: DRAFT.** Every team member edits this in a single PR, then approves that PR to signal
acceptance. Revisit after the review release (AGENTS.md §5) and whenever it stops matching
how we actually work. Placeholders are marked `_TBD_`.

Members: Sam Fiallos, Arda Dinc, Bryant Luna-Ramos, Karthik Ganeshan, Daniel Zhang.

## 1. Availability and effort

| Member | Typical hours/week on this project | Usual working windows (with time zone) | Known unavailability |
| --- | --- | --- | --- |
| Sam | ~5 | Tuesdays 4:00-9:00PM EST | N/A |
| Arda | _TBD_ | _TBD_ | _TBD_ |
| Bryant | _TBD_ | _TBD_ | _TBD_ |
| Karthik | ~5 | Thursdays 9:00-17:00 ET; async on GitHub other days | None known |
| Daniel | _TBD_ | _TBD_ | _TBD_ |

Expected effort is roughly equal across members over the whole project, not every week.
Coordinating a release, reviewing, and writing docs count the same as writing code.

## 2. Communication

- **Channel:** _TBD_ (e.g. a Slack/Discord channel) for day-to-day; GitHub Issues and PRs for
  anything that should be findable later; staff questions go to the course `#help` channel and
  the answer is copied into `docs/REQUIREMENTS.md` §4.
- **Response times:** acknowledge direct questions within _TBD_ hours on weekdays; PR reviews
  within 24 hours (AGENTS.md §3); if you will be offline more than 48 hours, say so in the
  channel and hand off anything "In progress".
- **Sync meeting:** _TBD_ (e.g. 20 minutes, twice a week). Agenda: what moved on the board,
  what is blocked, what needs a decision.

## 3. Decision-making

- Default is **consent, not consensus**: a proposal (in an issue or PR) stands unless someone
  raises a `blocking:` objection with a reason within one working day.
- Technical disagreements that are not resolved in two rounds of comments get a 15-minute
  call; if still unresolved, the owner of the affected area decides and writes down the
  decision and the alternative in `docs/REQUIREMENTS.md` §2 (the decisions table).
- Anything that changes the public API, a dependency, CI, or this agreement needs a second
  approval.

## 4. Coordination roles (rotate per milestone)

| Milestone | Coordinator (board, deadlines, staff contact) | Release coordinator | Fresh-checkout verifier |
| --- | --- | --- | --- |
| M1: first working version (Oct 7) | _TBD_ | _TBD_ | _TBD_ |
| Review release | _TBD_ | _TBD_ | _TBD_ |
| Final release | _TBD_ | _TBD_ (must differ from the review release coordinator) | _TBD_ |

Credential roles (Cloud project owner, calendar owner, GitHub admin) are listed in
`docs/HUMAN_STEPS.md` §0.

## 5. Blocked or unavailable

- Blocked for more than half a day → post in the channel with what you tried; anyone free
  pairs for 30 minutes. Blocked on staff/access → the milestone coordinator escalates the same day.
- Someone unavailable unexpectedly → their "In progress" issue goes back to Ready after 48
  hours of silence; the coordinator reassigns.
- Uneven participation or conflicts are raised first inside the team, then with staff if not
  resolved within a week. Sensitive concerns may go to staff privately.

## 6. How we work (summary; details in AGENTS.md)

Issue first, small branches, PR with the template, one approval and green CI to merge,
squash-merge, tagged releases with reviewed notes. Everyone reads and changes everyone else's
code; nobody "owns" a module in the sense of being the only person allowed to touch it.

## 7. What we learned from the release

_To be written after the review release: one observation about how the workflow worked, the
evidence (links to issues, reviews, releases), and the single adjustment we made in AGENTS.md._

## Acceptance

| Member | Accepted on (PR approval) |
| --- | --- |
| Sam Fiallos | _TBD_ |
| Arda Dinc | _TBD_ |
| Bryant Luna-Ramos | _TBD_ |
| Karthik Ganeshan | _TBD_ |
| Daniel Zhang | _TBD_ |
