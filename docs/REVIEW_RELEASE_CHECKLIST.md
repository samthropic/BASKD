# BASK'D: what we need to do next

Team 7 - October 14, 2026

## Are Levels 3-4 working?

**The main code mechanisms are already implemented and tested. We still need teammate review and a verified published release before calling the milestone complete.**

- **Level 3:** The API uses our own `CalendarProvider` interface and `Event` models. Google SDK calls and data conversion live behind that interface.
- **Level 4:** Startup supplies the provider to the API. Tests can supply the in-memory provider without Google credentials or network access.
- Our service already has `ports.py`, the Google and memory adapters, `create_app(provider=...)`, and FastAPI provider injection. We do not need a new provider or a new injection framework.
- [PR #15](https://github.com/samthropic/BASKD/pull/15) adds Get Event contract documentation and tests for both adapters and injection. [Its CI](https://github.com/samthropic/BASKD/actions/runs/38593477303) passed: 171 tests, 5 separate real-Google integration tests, lint, typing, and Docker.
- This evidence does not replace review of all five operations or the required human verification.

## Proposed task owners - please acknowledge or swap

These are proposed assignments, not commitments already accepted by the teammates.

### Sam: review the changes

- [ ] Review [PR #15](https://github.com/samthropic/BASKD/pull/15). Check that the read contract, implementation and tests agree; leave specific findings and approve only if satisfied.
- [ ] Review [PR #1](https://github.com/samthropic/BASKD/pull/1), including provider selection, injection, and tests that substitute the memory provider. Confirm the five interface operations have understandable contracts.
- [ ] Record substantive review evidence: what you checked, what worked, and anything that must change. A bare approval is not enough evidence for the assignment.

**Done when:** the PRs have an independent review and required concerns have a clear disposition.

### Daniel: coordinate integration and the review release

- [ ] Confirm which staff comments still need action and whether PR #1 is ready to merge. It currently says it is kept open for staff review; resolve that status before merging.
- [ ] After review, have the PR owners integrate #15 into `arda/milestone-1`, then integrate #1 into `main` under the repository's merge rules.
- [ ] Prepare release notes/changelog for the actual scope, including known gaps and links to PRs and verification. Merge those changes before selecting the release commit.
- [ ] Check CI and real-Google verification for the exact release commit. Create a new annotated tag such as `v0.1.0-rc.1`; never move the existing `v0.1.0-alpha.1` tag.
- [ ] Prepare a draft GitHub Release using that tag. Wait for Karthik's verification, attach its evidence, and publish with **Set as a pre-release** checked.

**Done when:** there is a published GitHub prerelease URL with the tag, matching commit SHA, notes, limitations, and verification/CI links.

### Karthik: independently verify the tagged release

- [ ] Review the provider boundary and real/test wiring with Sam; flag any contract gaps.
- [ ] Once Daniel has pushed the candidate tag, clone into a new directory and check out that exact tag.
- [ ] Follow the README from scratch: `uv sync --locked`, `make check`, provider setup, and startup.
- [ ] Run `uv run pytest -m integration -ra` and the documented Google-backed `make demo` workflow. Use the shared disposable test calendar and verify cleanup.
- [ ] Record tag, commit SHA, commands, expected/observed results, and failures. Share the verification evidence with Daniel before publication. Obtain credentials privately; do not post keys or secret values.

**Done when:** another teammate can reproduce the tagged version and the release links their actual results. CI alone does not replace this fresh-checkout verification.

### Arda: coordination and updates

- [ ] Share this checklist and get explicit acknowledgment of owners and availability.
- [ ] Explain your Get Event changes in #15 and address review feedback.
- [ ] Coordinate the separate Team 4 review below and identify who submits the single team submission.
- [ ] Post today's linked team update; submit your own personal reflection privately. Every member submits their own reflection.
- [ ] Record one release-process observation and any adjustment after the review release.

## Separate requirement: review Team 4 today

**Team 7 reviews Team 4 (Issue Tracker). Team 6 reviews us.**

- [ ] Sam: examine a required-operation change and provider-boundary/injection change; inspect the relevant tests and record evidence-based findings.
- [ ] Bryant: attempt Team 4's documented setup, fast tests and main workflow; save commands and actual results. Trace the relevant code, state changes and provider calls.
- [ ] Arda: combine the findings into one team review, have the team check it, and submit links to recorded feedback and execution evidence on Brightspace.

**Deadline: October 14, 11:59 p.m. ET.** If setup fails, record the exact failing command/error and continue inspecting the available code. Do not invent defects.

Responses to incoming feedback, plus one verified usability improvement arising from actual review difficulty, are due next Wednesday, October 21.

## Timing and scope

The review prerelease and Levels 3-4 are due October 14; the handout says milestones are due before class. The October 11 announcement says the release and personal/team updates are still due even though class does not meet this Wednesday. The sister-team review has its separate 11:59 p.m. deadline.

The review release may contain unfinished requirements if the notes identify them honestly. If the team cannot meet the release deadline, agree on an extension request and contact staff before the original deadline. An extension does not automatically move the sister-team review deadline.

Do not start automatic retries, idempotency, another real provider, or a large redesign for Levels 3-4. Level 5 is due October 21; useful sanitized failure logging is a concrete remaining area to inspect for that milestone.

## Sources

- [HW1 handout: Levels 3-4, teamwork, releases and milestones](https://docs.google.com/document/d/1vuoM1S8Xev2in-uudbdOJtW0VWWX1xNSuJ7bKmMcdQ0/edit)
- [HW1 rubric: especially sections 5, 8 and 11](https://docs.google.com/document/d/1GPKhoRi0g4KHOEYyYToOILW24Av-Cw7NHLMO7JhEEKA/edit)
- [Sister-team assignments](https://docs.google.com/spreadsheets/d/11tNEJ-kLH3HOVj_VvsNiSuBj7XAobqcLMKtLjxsMPtY/edit)
- [Brightspace review instructions and submission](https://brightspace.nyu.edu/d2l/lms/dropbox/user/folder_submit_files.d2l?db=1259621&grpid=0&isprv=0&bp=0&ou=625975)
- [Repository review/release procedure](https://github.com/samthropic/BASKD/blob/arda/milestone-1/AGENTS.md)

Prepared with Codex assistance. Owners should confirm these proposed tasks in this documentation PR before treating them as accepted commitments.
