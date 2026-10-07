# Contributing

Thanks for working on BASK'D. The short version:

1. **Set up** with the README quick start (`uv sync --locked`, `make check`). Provider
   credentials are optional for unit tests; see `docs/HUMAN_STEPS.md` to get them.
2. **Start from an issue** (templates in `.github/ISSUE_TEMPLATE/`). Pick one with an owner,
   size and reviewer, move it to "In progress", branch from `main` as `feat/…`, `fix/…`,
   `docs/…` or `chore/…`.
3. **Make the change** following the map in `AGENTS.md` §6 (which files to touch for which
   kind of change) and the conventions in §7. Add or adjust tests at every layer you touched;
   update the README/docs where a user would look; add a line to `CHANGELOG.md` "Unreleased".
4. **Before pushing:** `make fmt && make check`. Never commit anything under `secrets/` or a
   `.env` file.
5. **Open a pull request** with the template filled in and `Closes #N`. One behaviour per PR,
   ideally under ~400 changed lines. CI must be green; one approval from someone who did not
   write the code; squash-merge.

Everything else (review rules, versioning, release procedure, how we handle a defective
release, how coding agents should work here) is in [`AGENTS.md`](AGENTS.md). How we work as a
team is in [`docs/TEAM_AGREEMENT.md`](docs/TEAM_AGREEMENT.md).
