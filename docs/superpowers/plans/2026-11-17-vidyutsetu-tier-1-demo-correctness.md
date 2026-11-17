# VidyutSetu Tier 1 Demo and Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a credible, real-backend demo path and close Tier 1 health, ML-artifact, adapter-correctness, and frontend defects.

**Architecture:** Keep FastAPI and the current adapters/ML service intact. Exercise the live app with the existing Playwright setup, and extend existing pytest modules for health, artifacts, and sample correctness.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, pytest, scikit-learn, xgboost, SHAP, vanilla JavaScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-ami-workbench-quality-hardening-design.md`

## Global Constraints

- Work locally on `ml-upgrade`; do not pull, push, merge, or rebase.
- Preserve existing worktree changes and API response shapes.
- Keep training/evaluation labeled **SYNTHETIC**; do not claim real-data performance.
- Do not hand-edit `metrics.json`; generate it from an actual holdout evaluation.
- Read training versions from saved artifacts; use `unknown` when an artifact cannot prove them.
- Keep `scikit-learn==1.9.1` and `xgboost==3.4.1`; pin SHAP exactly.
- Preserve `backend/static/tailwind.css`; build to a temporary output for checks.
- Add focused tests for each behavior and commit scoped changes locally.

## Review Focus

- DB failure must affect readiness but not liveness; `/ready` and `/api/health` remain compatible. Test all four endpoint outcomes in Task 2.
- Artifact metadata absent/unknown must not be guessed from the active interpreter. Test unknown metadata and proven mismatches in Task 3.
- Synthetic data and model explanations must remain explicitly advisory. Test labels and exact `method` values in Task 3.
- Faulty samples must produce the intended rule/event finding and preserve energy/time semantics after conversion. Test each checked-in abnormal sample in Task 5.
- At 320–768px, hidden tabs/modal content must not cause horizontal overflow or lose keyboard focus. Test the viewport set and keyboard paths in Task 6.

---

### Task 1: Record the verified baseline matrix

**Files:**
- Create: `docs/QA_COMPLETION_MATRIX.md`

**Interfaces:**
- Consumes: the baseline `git status`, `git log -5`, `pytest -q`, file inventory, frontend checks, Playwright run, Docker probe, and inspected source/artifact evidence.
- Produces: the initial DONE/PARTIAL/NOT DONE/BLOCKED table for all 18 requested areas, with actual commands/output and no claims based on the existing audit reports.

- [ ] **Step 1: Write the baseline matrix before product changes**

Record the baseline outputs exactly: branch `ml-upgrade` is five commits behind; 119 passed/4 skipped/601 warnings; frontend check passed with outdated Browserslist warning; existing Playwright passed its narrower flow; Docker daemon unavailable. Include the 18 requested rows, file evidence, test scope, and which checks have not run. Note that `npm run check:frontend` rewrote the pre-existing untracked `tailwind.css`.

- [ ] **Step 2: Verify the matrix against captured command outputs**

Check each count, status, and path against the actual baseline evidence in this conversation. Do not copy claims from `docs/COMPLETE_ENGINEERING_AUDIT.md` or `docs/IMPLEMENTATION_VERIFICATION_REPORT.md`.

- [ ] **Step 3: Commit the baseline record**

```bash
git add docs/QA_COMPLETION_MATRIX.md
git diff --cached --check
git commit -m "docs: record verified QA baseline"
```

### Task 2: Correct service health semantics

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_api_and_engine.py`

**Interfaces:**
- Consumes: existing SQLAlchemy `engine`; existing `/ready` and `/api/health` handlers.
- Produces: `/health/live` liveness (200 independent of DB), `/health/ready` readiness (503 on DB failure), `/ready` compatibility alias, and `/health` with the existing JSON keys but `status: error` plus HTTP 503 when DB is down.

- [ ] **Step 1: Update health tests first**

Update `test_service_health_reports_database_error` to assert HTTP 503, JSON keys `status`, `version`, `db`, and values `error`, `app.version`, `error`. Add tests proving `/health/live` remains 200 with a failed DB, `/health/ready` is 503, `/ready` still responds, and `/api/health` retains its healthy response.

- [ ] **Step 2: Run the focused tests**

Run: `pytest tests/test_api_and_engine.py -q`
Expected: new failure on the old `/health` behavior and missing health routes; existing `/ready` and `/api/health` assertions remain meaningful.

- [ ] **Step 3: Implement only the health handlers**

Keep `/health`'s response keys stable. Reuse the DB probe for readiness; make liveness independent of the DB. Do not remove `/ready`.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_api_and_engine.py -q`
Expected: all tests in the module pass.

```bash
git add backend/main.py tests/test_api_and_engine.py
git diff --cached --check
git commit -m "fix: report database health accurately"
```

### Task 3: Enforce artifact provenance and truthful explanations

**Files:**
- Modify: `requirements.txt`, `ml_training/train.py`, `app/ml/inference.py`, `backend/api/ml_routes.py`
- Test: `tests/test_ml_training.py`, `tests/test_ml_api.py`, `tests/test_batch_b_analytics.py`

**Interfaces:**
- Consumes: existing `feature_schema.json`, model artifact files, `MLArtifactsError`, and `POST /ml/explain`.
- Produces: saved `training_versions` metadata sourced from the serialized artifacts during training/export; runtime status exposes `unknown` if legacy artifacts do not prove a version; proven mismatches raise `MLArtifactsError` before predictions. `POST /ml/explain` keeps its response shape and returns `method` exactly `shap` or `feature_importance_fallback`.

- [ ] **Step 1: Add failing provenance and method tests**

Test a known-compatible artifact, a proven incompatible version, legacy/unknown version metadata, import/load failure, and both explanation methods. Assert that an explanation method is present and uses only the two exact allowed strings. Keep `is_synthetic` true for the checked-in model artifacts.

- [ ] **Step 2: Run focused tests and observe failures**

Run: `pytest tests/test_ml_training.py tests/test_ml_api.py tests/test_batch_b_analytics.py -q`
Expected: method-name and metadata assertions fail until implementation.

- [ ] **Step 3: Inspect saved artifacts and record only proven versions**

Inspect the saved classifier and detector metadata without substituting current package versions. In `ml_training/train.py`, export proven versions with the feature schema for newly trained artifacts; represent unprovable legacy versions as `unknown`. Add a clear runtime mismatch error before serving predictions. Pin `shap==0.54.1` in `requirements.txt`, matching the installed baseline version.

- [ ] **Step 4: Implement the stable explanation method field**

In `app/ml/inference.py`/`backend/api/ml_routes.py`, report `shap` when SHAP actually produced the explanation and `feature_importance_fallback` when the approximation was used. Keep the existing explanation payload fields and label fallback truthfully.

- [ ] **Step 5: Run focused tests and artifact smoke test**

Run: `pytest tests/test_ml_training.py tests/test_ml_api.py tests/test_batch_b_analytics.py -q`
Run: `.\.venv\Scripts\python.exe -c "from app.ml.inference import _load_models; _load_models(str(__import__('pathlib').Path('app/ml/artifacts').resolve())); print('artifact load ok')"`
Expected: focused tests pass and the actual checked-in model files load; report any recorded version as `unknown` unless verified from those files.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt ml_training/train.py app/ml/inference.py backend/api/ml_routes.py tests/test_ml_training.py tests/test_ml_api.py tests/test_batch_b_analytics.py
git diff --cached --check
git commit -m "fix: validate model provenance and explain method"
```

### Task 4: Generate threshold analysis from a real holdout

**Files:**
- Modify: `ml_training/train.py`
- Create: `docs/ml/anomaly_thresholds.md`
- Test: `tests/test_ml_training.py`

**Interfaces:**
- Consumes: meter-disjoint validation/test split and existing anomaly score functions.
- Produces: generated `metrics.json` threshold rows with threshold, precision, recall, alert count, and alert rate; documentation is rendered from that generated JSON.

- [ ] **Step 1: Test threshold-row calculations**

Add a small deterministic helper test asserting each threshold's predicted alert count/rate and precision/recall from explicit scores and labels, including no-alert and all-alert thresholds.

- [ ] **Step 2: Verify the test fails**

Run: `pytest tests/test_ml_training.py -q`
Expected: threshold-view helper/fields are absent.

- [ ] **Step 3: Add the holdout threshold analysis**

Compute the threshold table from the real grouped validation holdout. Store numeric results in `metrics.json` through the training code only; label the source data SYNTHETIC and preserve the existing threshold-selection behavior.

- [ ] **Step 4: Run an actual training/evaluation export**

```powershell
$mlOutput = Join-Path $env:TEMP 'vidyutsetu-ml-evaluation'
.\.venv\Scripts\python.exe -m ml_training.train --data-csv data\ami_payload_dataset_synthetic.csv --output-dir $mlOutput
```
Expected: command completes using the checked-in synthetic dataset and emits model/evaluation artifacts. Do not hand-edit its JSON. If the full run fails, report the exact error and do not claim results.

- [ ] **Step 5: Generate the report from the run output**

Create `docs/ml/anomaly_thresholds.md` from the generated metrics file, including the actual precision, recall, alert count/rate rows and threshold trade-off. Identify the data as SYNTHETIC and explicitly avoid real-world claims.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_ml_training.py -q`
Review the generated JSON/report together and commit the training code, tests, and report (not temporary model files).

### Task 5: Audit abnormal vendor samples and semantic round-trips

**Files:**
- Modify: `tests/test_adapters.py`, `tests/test_roundtrip_directed.py`
- Create if needed: `tests/test_sample_correctness.py`
- Modify only if tests reproduce a defect: `backend/adapters/`, `backend/engine/`

**Interfaces:**
- Consumes: checked-in payloads under `samples/`, adapter parsers, `ValidationEngine`, and existing directed round-trip fixtures.
- Produces: regression coverage for every injected fault present in the Alpha tamper and Beta anomaly samples, plus timestamp and energy preservation through Alpha/Beta/Gamma/Delta conversion.

- [ ] **Step 1: Add tests using the checked-in sample files**

Load `samples/alpha_hes_tamper.json` and `samples/beta_hes_anomaly.csv` from disk. Assert the Alpha magnetic-tamper event and Beta rollback/out-of-range reading are surfaced by the actual parser/validator. Assert each applicable sample finding is present; do not duplicate or rewrite fixture values in the test.

- [ ] **Step 2: Run tests to identify misses**

Run: `pytest tests/test_adapters.py tests/test_roundtrip_directed.py tests/test_sample_correctness.py -q`
Expected: current misses fail with the specific sample and missing finding/value named.

- [ ] **Step 3: Fix only reproduced adapter/validator defects**

Preserve existing conversion behavior and response shapes. For each fix, retain a regression assertion from Step 1 and compare energy/timestamp semantics against the directed suite.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_adapters.py tests/test_roundtrip_directed.py tests/test_sample_correctness.py -q`
Expected: all abnormal-sample checks and directed cross-vendor assertions pass.

### Task 6: Fix responsive navigation, modal, and named frontend reliability defects

**Files:**
- Modify: `backend/static/app.js`, `backend/static/dashboard.html`
- Test: extend `tests/browser/workbench.spec.cjs`

**Interfaces:**
- Consumes: existing `switchTab`, run-detail modal, upload input, generation/round-trip handlers, and Playwright runner.
- Produces: one scrollable tab container with active-tab visibility; a focus-managed modal; tab keyboard behavior; visible, truthful async errors; restricted file picker; no unused Chart.js; pinned external asset versions.

- [ ] **Step 1: Add Playwright assertions before implementation**

Assert no page overflow at 320, 360, 375, 390, 430, and 768px; one horizontal tab scroll container with no overlapping hint; selected tab is scrolled into view. Test all nine tabs' ARIA relationships, roving tabindex, Left/Right wrapping, Home/End. Test detail-modal focus-in, Tab/Shift+Tab trap, Escape close, trigger focus restore, and 360px fit. Test rejected clipboard writes never announce success, failed synthetic generation shows a visible error, round-trip sample HTTP errors are visible, and the file input accepts JSON/CSV only.

- [ ] **Step 2: Run the browser test to establish failures**

Run: `npm run test:browser`
Expected: assertions fail only on unimplemented requirements; capture console errors and screenshot on failure.

- [ ] **Step 3: Implement VY-01, VY-02, VY-04–07, VY-08, VY-09, and VY-10**

Keep the existing dialog role and do not add redundant ARIA. Remove redundant tab pseudo-element hints, focus the active tab into view, use native scroll without clipping, and implement roving keyboard semantics for the nine named sections. Keep visible error handling on round-trip sample load. Preserve the existing clipboard fallback and accepted file types. Confirm Chart.js is unused before removing any reference; pin the actual Lucide CDN version without introducing an unverified asset.

- [ ] **Step 4: Run browser and build checks**

Run: `npm run test:browser`
Run: `node --check backend/static/app.js`
Run Tailwind CLI with `-o` directed to a temporary file; do not run the script that overwrites the pre-existing `tailwind.css`.
Expected: all frontend assertions pass; no browser console errors on the tested flows.

- [ ] **Step 5: Commit**

```bash
git add backend/static/app.js backend/static/dashboard.html tests/browser/workbench.spec.cjs
git diff --cached --check
git commit -m "fix: harden workbench keyboard and mobile flows"
```

### Task 7: Exercise the complete live demo path

**Files:**
- Create: `tests/e2e/workbench.spec.cjs` (or extend `tests/browser/workbench.spec.cjs` if the existing harness supports the full path cleanly)
- Modify: `package.json` only if a distinct E2E command is needed

**Interfaces:**
- Consumes: real FastAPI app, temporary SQLite database, real login, sample payloads, and Task 5 UI behavior.
- Produces: an automated run at 1440px and 360px: login → upload a supported file and load each vendor sample → validate/findings → source-to-target transform → history → HTML report export.

- [ ] **Step 1: Write the real-app workflow test**

Launch FastAPI with a temporary database and test credentials. For all four vendors, load an existing sample, validate it, and verify findings/results. Upload a supported sample file and exercise upload-to-validation-to-history-to-report. Transform from source to target, find the run in history, and verify the exported report is HTML. Repeat the required flow at both viewport sizes. Capture console errors and save a screenshot on failure.

- [ ] **Step 2: Run and inspect the failing E2E**

Run: `npm run test:e2e` (or the chosen existing browser script).
Expected: the harness proves any missing selectors, test-data incompatibility, or UX defect against the live API.

- [ ] **Step 3: Fix only reproduced demo blockers**

Use the real API responses and existing samples. Do not stub network calls or insert mock findings.

- [ ] **Step 4: Verify the full Tier 1 gate**

Run: `pytest -q`
Run: `npm run test:e2e`
Run: `node --check backend/static/app.js` and the temporary-output Tailwind build.
Expected: all backend tests pass, all required browser flows pass at both widths, and no frontend build error. Record skipped tests, warnings, and Docker-dependent checks as such.

- [ ] **Step 5: Commit the Tier 1 evidence**

Review the staged diff to exclude `vidyutsetu.db-wal`, `vidyutsetu.db-shm`, `backend/static/tailwind.css`, and unrelated pre-existing changes. Commit only scoped, verified Tier 1 files.
