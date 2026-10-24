# Release validation

Release checks should find regressions, not turn implementation details into
permanent product requirements. A release is not the first time to run the broad
baseline: keep the ordinary CI unit, lint, type, and build jobs green during
development.

## Qualification matrix

1. Record the previous private release tag and the candidate commit/tree.
2. Audit the complete release range for affected boundaries. A documentation-only
   preparation commit does not excuse untested runtime changes earlier in that
   range.
3. Run the baseline in `AGENTS.md`: backend and frontend unit suites, Ruff checks,
   all package type checks, Svelte checks, production/standalone builds, and
   `uv run python scripts/changelog.py --check`.
4. Add service contracts for companion-service changes; runtime integration/E2E
   for orchestration, recovery, and hook changes; canonical replay for Chat v2;
   SQLite and PostgreSQL checks for schema/locking changes; isolated installs for
   package boundaries; and focused browser flows for affected rendering/state.
   Use the full scenario suites for broad protocol/runtime changes. Reuse
   evidence only when it identifies the exact tested tree and remains applicable.
5. Distinguish failures, intentional feature skips, and unavailable prerequisites.
   Do not report skipped service or device coverage as successful qualification.
   Unexplained regressions remain release blockers.

Use bounded parallel workers appropriate to the machine. Keep file-local
fixtures together when using pytest-xdist (`--dist loadfile`). Do not run
multiple overlapping full baselines while debugging one failing boundary.
Stop a stalled run deliberately, preserve its log, and report that it was
interrupted rather than treating partial progress as a pass.

The focused release-browser acceptance test uses the real `/docs/changelog`
route with isolated API fixtures. It can run against either the compiled app or
Vite: `cd ui && npx playwright test e2e/changelog.spec.ts`. Set `COGNIS_E2E_URL`
when the app is not at the default `http://localhost:8080`. Browser tests in
`ui/e2e/` must not depend on development-only module endpoints.

## Failure triage

Classify each failure before editing:

| Failure | Correct response |
|---|---|
| Behavior, security, persistence, or recovery regression | Fix implementation and add/retain a reproducer |
| Fixture omits a newly required field or authorization provenance | Align the fixture with the real model; retain negative access tests |
| Test asserts obsolete UI or transport details | Verify the supported contract and test it through the owning boundary |
| Timing or shared-state flake | Isolate clocks, events, storage, and worker state; do not just increase limits |
| Missing service, key, database, browser, or device | Record the prerequisite and rerun in a qualified environment |

Prefer parsed query parameters over URL-string ordering, rendered accessible
controls over private component names, and shared style ownership over duplicate
pixel-string checks. Assert visible state transitions and deny paths. Avoid
source-text contracts when a behavioral test can establish the same invariant.
Do not replace one obsolete UI snapshot with another equally brittle snapshot.

## Evidence

Record:

- candidate and base revision, interpreter/runtime versions;
- exact commands and outcomes (counts, duration, skips);
- each original failure, verified cause, correction, and rerun result;
- unavailable prerequisites and the precise unverified boundary;
- reviewer identity/session, reviewed tree, findings, and their disposition.

Release notes are prepared independently of publishing. Follow
[`changelog.d/README.md`](../../changelog.d/README.md) to preview/export the
candidate notes. Finalizing fragments, bumping packages, tagging, pushing,
publishing a release, and deploying are separate explicit actions.
