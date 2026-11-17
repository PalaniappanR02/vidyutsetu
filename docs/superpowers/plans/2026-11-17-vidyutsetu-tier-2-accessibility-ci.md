# VidyutSetu Tier 2 Accessibility and CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify authorization at every protected endpoint, complete the accessible unified UI, and extend existing CI/test architecture.

**Architecture:** Build authorization tests around actual FastAPI requests and the current role fixtures. Use rendered-page/browser evidence for contrast and accessibility. Extend the existing workflow in place.

**Tech Stack:** FastAPI, pytest, Playwright, vanilla CSS/JavaScript, GitHub Actions, Docker.

**Spec:** `docs/superpowers/specs/2026-11-17-ami-workbench-quality-hardening-design.md`

## Global Constraints

- Do not begin Tier 2 until Tier 1's tests and Playwright demo gate pass.
- Preserve all existing API contracts and current worktree changes.
- Keep `backend/static/tailwind.css` unchanged; build checks must target a temporary file.
- Use only real backend calls in demo tests and label all ML evidence SYNTHETIC.
- Do not replace `.github/workflows/ci.yml`; extend its existing checks.
- Any Docker rollback/volume commands remain BLOCKED locally while the daemon is unavailable.
- Commit scoped changes locally and do not stage database sidecars or unrelated files.

## Review Focus

- A role may have read access but not write access; test every protected endpoint for each role in Task 1.
- An endpoint may return a misleading 200 with an error body; assert both status and response semantics in Task 1.
- Browser-computed foreground/background colors can inherit from ancestors or dark mode; calculate resolved visible pairs in Task 2.
- Two tablists coexist in the dashboard; keyboard movement must stay within the focused tablist in Task 2.
- Docker health/build may pass in CI but cannot be claimed locally without a daemon; keep local and CI evidence distinct in Task 3.

---

### Task 1: Verify role permissions endpoint-by-endpoint

**Files:**
- Modify: `tests/test_auth.py`
- Test: `backend/security/auth.py`, `backend/api/routes.py`, `backend/api/ml_routes.py`
- Modify: `docs/SECURITY_AND_ACCESS.md` only after results are known

**Interfaces:**
- Consumes: real test app, user fixture/database, CSRF/session logic, current route contracts.
- Produces: a test matrix for unauthenticated, viewer, operator, and admin requests to every protected read/write/admin endpoint.

- [ ] **Step 1: Enumerate protected routes from the mounted app**

Add a test fixture/table containing every registered endpoint and a valid request payload where needed. Cover `/api/health`, `/api/stats`, `/api/vendors`, `/api/generate`, `/api/workbench/execute`, `/api/compare`, `/api/roundtrip`, both `/api/suites` methods, `/api/suites/{suite_id}/run`, all `/api/test-runs` list/detail/report routes, `/ml/health`, `/ml/validate`, `/ml/validate-batch`, `/ml/explain`, `/ml/meters`, `/ml/meters/{meter_id}/profile`, and every `/auth` route (`/login`, `/me`, `/logout`, users, audit, analytics). Exercise endpoints as unauthenticated, viewer, operator, and admin clients; assert public routes remain public and protected routes allow/deny as expected.

- [ ] **Step 2: Assert each route as each principal**

For every route, exercise unauthenticated, viewer, operator, and admin clients; assert allowed status and denied status, with CSRF headers for cookie-authenticated writes. Do not infer the result from `Depends` declarations.

- [ ] **Step 3: Run the matrix and resolve real policy mismatches**

Run: `pytest tests/test_auth.py -q`
Expected: the result is an explicit allowed/denied matrix. Fix only authorization behavior that conflicts with the approved existing policy; update documentation to match passing tests.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_auth.py -q`
Run: `pytest -q`
Expected: matrix and full suite pass.

### Task 2: Finish accessibility and design-token unification

**Files:**
- Modify: `backend/static/start.html`, `backend/static/dashboard.html`, `backend/static/index.html`
- Create if needed: `backend/static/design-tokens.css`, `tests/browser/contrast-audit.cjs`, `docs/accessibility/contrast-audit.md`
- Test: extend `tests/browser/workbench.spec.cjs`

**Interfaces:**
- Consumes: Tier 1 tab/modal behavior, actual browser rendering, existing page styles.
- Produces: VY-11 contrast evidence and 4.5:1 text pairs, VY-12 skip link, and shared ivory/forest-green/terracotta tokens across the three pages.

- [ ] **Step 1: Capture actual before contrast pairs**

Use Playwright against the rendered `start.html`, `dashboard.html`, and `index.html` at representative desktop/mobile sizes and each supported theme. Resolve inherited foreground and nearest opaque background for visible text, calculate WCAG contrast ratios, and write the generated “before” table to `docs/accessibility/contrast-audit.md`.

- [ ] **Step 2: Add tests for VY-12 and contrast**

Assert the skip link is the first keyboard-reachable content control on `index.html`, points to the main content, and works on activation. Assert every audited visible text pair reaches at least 4.5:1 after the change; keep excluded decorative/icon-only elements out of the text audit with an explicit rule.

- [ ] **Step 3: Add shared design tokens and minimal contrast corrections**

Centralize the three page palettes in a shared static CSS file, retain the established ivory background/forest-green primary/terracotta accent, and darken low-contrast text minimally. Link the shared stylesheet from each page and remove duplicate conflicting token definitions.

- [ ] **Step 4: Generate and verify the after table**

Run the same browser calculation and update the after table from its output, not manual estimates. Run: `npm run test:browser`; run `node --check backend/static/app.js` and a temporary-output Tailwind build.
Expected: no audited visible text pair below 4.5:1, skip link passes, and page overflow checks remain clear.

- [ ] **Step 5: Commit**

Stage the three HTML pages, shared tokens, audit script/report, and test changes only. Exclude `tailwind.css`. Commit after `git diff --cached --check`.

### Task 3: Add test architecture, coverage, and container CI checks

**Files:**
- Modify: `pytest.ini`, `requirements.txt`, `.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml`, `backend/main.py`
- Create: `docs/testing/test_architecture.md`
- Test: existing backend and Playwright suites

**Interfaces:**
- Consumes: existing CI jobs for Python tests, npm build/browser, and dependency audit; current non-root Docker image.
- Produces: named pytest markers, coverage configuration/command, Docker `$PORT` defaulting to 8000, `/health/ready` HEALTHCHECK, explicit Compose limits, and CI Docker build/container smoke coverage.

- [ ] **Step 1: Configure pytest markers and coverage**

Register markers used by the suite (at minimum `unit`, `integration`, `ml`, `browser`, and `slow` as applied). Add the `pytest-cov` dependency only if missing, configure coverage in `pyproject.toml` or `.coveragerc`, and document exclusions and the actual command in `docs/testing/test_architecture.md`.

- [ ] **Step 2: Verify coverage locally**

Run: `pytest --cov=backend --cov=app/ml --cov-report=term-missing -q`
Expected: report measured coverage and pass/fail from the configured policy; never invent or hardcode the measured percentage.

- [ ] **Step 3: Implement and test container port/health/limits**

Keep the existing non-root user. Make the Uvicorn command honor `$PORT` with default 8000 and point Docker HEALTHCHECK/Compose healthcheck to `/health/ready` on that port. Set initial Compose guardrails to `cpus: 1.0` and `mem_limit: 512m`; document these as configuration limits, not measured capacity claims.

- [ ] **Step 4: Extend the existing CI workflow**

Retain existing pytest, pip-audit, frontend build, Chromium, and browser steps. Add coverage execution and Docker build plus an ephemeral container smoke check that waits for `/health/ready` to return 200. Ensure cleanup runs even when smoke checks fail.

- [ ] **Step 5: Run locally available checks and report Docker boundary**

Run: `pytest -q`
Run: `pytest --cov=backend --cov=app/ml --cov-report=term-missing -q`
Run: `npm run test:browser`
Run frontend syntax and temporary-output build.
Run: `docker version` only to report daemon availability.
Expected: non-Docker checks pass; if the daemon remains unavailable, local image/smoke checks are BLOCKED. Do not state that CI passed unless an actual workflow run is observed.

- [ ] **Step 6: Verify Tier 2 gate and commit**

Review staged files, excluding generated `tailwind.css` and database sidecars. Commit the scoped Tier 2 changes after all locally runnable checks pass.
