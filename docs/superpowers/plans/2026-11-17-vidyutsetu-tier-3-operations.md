# VidyutSetu Tier 3 Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add measured operational evidence, release/rollback procedures, backup/restore verification, and honest drift monitoring after Tiers 1 and 2 pass.

**Architecture:** Use the real FastAPI app and temporary SQLite databases for load and recovery checks. Generate release/ML evidence from repository artifacts; document Docker operations without claiming unexecuted commands work.

**Tech Stack:** FastAPI, SQLite, pytest, Python standard library/httpx, Docker documentation, JSON logs/metrics.

**Spec:** `docs/superpowers/specs/2026-11-17-ami-workbench-quality-hardening-design.md`

## Global Constraints

- Do not begin Tier 3 until Tier 1 and Tier 2 verification is complete.
- No invented load numbers, training results, real-data claims, or certifications.
- Docker volume rollback/backup commands must be labeled **BLOCKED** until run with a working daemon.
- Keep the SYNTHETIC label on model training/evaluation; do not modify ML metrics by hand.
- Preserve API contracts; any metrics route is additive and must not expose payloads, credentials, or raw user data.
- Keep existing database files and worktree changes; use disposable temporary DBs for tests.
- Commit scoped, verified Tier 3 changes locally; do not push.

## Review Focus

- Load-test requests must exercise real responses and isolate their DB; assert no unexpected status or silent failures in Task 1.
- P95/throughput values vary by environment; report actual output and environment without pass claims based on invented thresholds in Task 1.
- Metrics cardinality must remain bounded to route templates/status classes and must not contain raw URLs or payloads in Task 2.
- Backup restore must preserve actual SQLite schema and representative rows in a separate temporary file; test integrity in Task 3.
- Drift output from synthetic or sparse histories is advisory, never a claim of real-data calibration; test its labeling and empty-history behavior in Task 4.

---

### Task 1: Measure basic real-app load

**Files:**
- Create: `tests/load/run_load.py`
- Modify: `README.md` Roadmap / Known Limitations only if a limitation is demonstrated

**Interfaces:**
- Consumes: the running FastAPI app, local temporary SQLite DB, authenticated demo/operator session, and existing workbench/health endpoints.
- Produces: command-line load run reporting request count, errors, throughput, and latency percentiles from real responses.

- [ ] **Step 1: Implement the load runner with explicit options**

Use standard-library concurrency or existing `httpx`; accept base URL, duration, and concurrency as CLI options. Authenticate using a disposable test account. Exercise read-only health and a bounded real workbench request; do not use mocked response data.

- [ ] **Step 2: Test calculations without fabricating performance claims**

Unit-test percentile and error-count calculations with explicit small in-memory timing inputs. Keep unit-test values separate from the actual load report.

- [ ] **Step 3: Run against the local app**

Run the app with a temporary DB and execute `python tests/load/run_load.py --base-url http://127.0.0.1:8765 --duration-seconds 30 --concurrency 5`.
Expected: printed values come from the actual run; capture OS, Python version, app commit, and test shape. If the app/server cannot run, report failure and do not invent a result.

- [ ] **Step 4: Commit the load harness and measured report**

Add a report only if Step 3 actually completes. Commit the script and report with their measured provenance.

### Task 2: Add structured request logging and measured metrics

**Files:**
- Modify: `backend/main.py`
- Create if needed: `backend/observability.py`, `tests/test_observability.py`
- Create: `docs/sre/observability.md`

**Interfaces:**
- Consumes: existing request ID middleware and `LOGGER` extras (`request_id`, route template, status, duration).
- Produces: one-line structured JSON request logs and an additive metrics endpoint with bounded route-template/status counters and duration observations.

- [ ] **Step 1: Test JSON log shape and metric behavior**

Use captured logs and sequential test requests to assert valid JSON contains request ID, method, route template, status, and duration; assert no payload, password, cookie, or raw query values appear. Assert counters/durations change only after requests.

- [ ] **Step 2: Implement bounded observability**

Format only approved fields. Aggregate by route template and status class, not raw path/query. Document that in-process metrics reset on restart and are not shared across workers.

- [ ] **Step 3: Verify and commit**

Run: `pytest tests/test_observability.py tests/test_api_and_engine.py -q`
Expected: logs parse as JSON and metrics reflect the test requests.
Commit the scoped implementation/tests/docs.

### Task 3: Create release manifest and recovery procedures

**Files:**
- Create: `docs/release/manifest.json`, `docs/release/rollback.md`, `docs/sre/backup-restore.md`
- Create: `scripts/build_release_manifest.py`
- Create: `tests/test_database_backup_restore.py`
- Test: `tests/test_release_manifest.py`
- Modify if required: `backend/db/database.py`

**Interfaces:**
- Consumes: app version, locked/pinned dependencies, model artifact files, SQLite database.
- Produces: a provenance manifest and a tested SQLite backup/restore path; Docker commands are present for operators but explicitly BLOCKED locally.

- [ ] **Step 1: Test SQLite backup/restore**

Create a temporary DB with representative schema and row data, back it up with SQLite's backup API, restore to a second temporary path, and assert `PRAGMA integrity_check`, table presence, and row equality.

- [ ] **Step 2: Implement only required recovery helpers**

Reuse SQLite backup APIs and existing SQLAlchemy configuration. Do not copy live database sidecars or overwrite the user's current DB.

- [ ] **Step 3: Generate the release manifest from real files**

Add `scripts/build_release_manifest.py` to read app version, Python/dependency versions, model artifact SHA-256 values, current test/build evidence, and source commit when available. Generate `docs/release/manifest.json` from those values. Mark dirty worktree or unavailable CI evidence honestly; do not label it a release certification. Unit-test the generator against a temporary artifact tree.

- [ ] **Step 4: Document blocked Docker procedures**

Write volume backup, restore, and prior-image rollback commands for the documented Docker deployment. Prefix each command block and the procedure with **BLOCKED — Docker daemon unavailable; not executed**. Include prerequisites and recovery verification without claiming success.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_database_backup_restore.py tests/test_release_manifest.py -q`
Validate the manifest against actual files and dependencies. Keep Docker rollback checks marked blocked. Commit release and SRE artifacts.

### Task 4: Document and test drift-monitoring limits

**Files:**
- Modify: `backend/api/ml_routes.py` only if a narrow status field is needed
- Test: `tests/test_ml_api.py`
- Create: `docs/sre/drift-monitoring.md`
- Modify: `README.md` Roadmap / Known Limitations as needed

**Interfaces:**
- Consumes: existing `/ml/meters/{meter_id}/profile` arrival-order behavior and actual stored meter readings.
- Produces: documented drift indicators, data-volume constraints, SYNTHETIC/live-data labels, and tests for sparse/empty histories.

- [ ] **Step 1: Test actual profile edge cases**

Assert one-reading and sparse-history behavior, ordered timestamp/arrival data, and missing fields. Verify no real-data calibration claim is returned for synthetic or insufficient history.

- [ ] **Step 2: Implement only a reproduced monitoring gap**

Prefer the existing meter profile over a second drift subsystem. Any added response fields are additive and must be derived from actual readings.

- [ ] **Step 3: Write operational guidance from measured behavior**

Document what the current profile can and cannot detect, required sample volume, alert interpretation, and that synthetic evaluation is not real-data calibration.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_ml_api.py -q`
Expected: edge cases and synthetic labels pass. Commit only after the Tier 3 review and test evidence is recorded.

### Task 5: Publish the final evidence matrix and repository state

**Files:**
- Modify: `docs/QA_COMPLETION_MATRIX.md`
- Modify: `README.md` Roadmap / Known Limitations

**Interfaces:**
- Consumes: the baseline matrix plus actual Tier 1/2/3 test, build, browser, security, Docker, load, and artifact results.
- Produces: final DONE/PARTIAL/NOT DONE/BLOCKED verdicts for all requested areas, explicit failures and regressions, commands/output, items not executed, risks, final git status, and diff stat.

- [ ] **Step 1: Update each matrix row from observed evidence**

Use only commands actually run. Distinguish locally passed checks, CI definitions that were not executed, Docker-blocked procedures, and synthetic-only ML evidence. Include actual measured load and contrast tables only if generated by their real runs.

- [ ] **Step 2: Update remaining risks**

List absent real AMI data, any unknown saved artifact versions, unexecuted CI/Docker checks, and any unverified operating assumptions in README Roadmap / Known Limitations. Do not claim real-data calibration or production certification.

- [ ] **Step 3: Verify final repository evidence**

Run: `pytest -q`
Run the browser E2E and frontend syntax/build checks.
Run: `git status --short`
Run: `git diff --stat`
Expected: report exact output; retain uncommitted user files if unrelated and never include database sidecars or the preserved Tailwind asset in commits.

- [ ] **Step 4: Commit the final report**

Stage only the final matrix and directly related README changes; commit after `git diff --cached --check`.
