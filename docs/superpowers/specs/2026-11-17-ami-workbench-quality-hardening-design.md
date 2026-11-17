# AMI Workbench Quality Hardening

## Intent

Make the existing VidyutSetu pre-integration workbench credible in a live BESCOM
demo by verifying its real API and UI flows, correcting documented defects, and
making test, ML, and operational claims traceable to repository evidence.

## Goals

- Preserve the current architecture, working features, API response shapes, and
  pre-existing worktree changes.
- Complete the explicit Tier 1 demo, adapter-correctness, ML-honesty, health, and
  frontend requirements before moving to Tier 2.
- Complete Tier 2 role-access verification, guided real-backend UX, accessibility,
  design-token, CI, and test-architecture work before Tier 3.
- Add Tier 3 load, release, rollback, SRE, and drift-monitoring deliverables only
  after Tiers 1 and 2 have been verified.
- Label all model training/evaluation data as SYNTHETIC and derive reported
  evaluation values from actual runs and artifacts.
- Keep a completion matrix with commands, observed output, defects, regressions,
  skipped checks, and remaining risks.

## Non-goals and anti-goals

- No rewrite, fabricated metrics, mock-data demo flow, claimed certification, or
  real-data performance claims.
- No remote git operations, API-contract redesign, deletion of pre-existing
  changes, or Docker-dependent success claims without a functioning daemon.
- No Tier 3 work before Tier 1 and Tier 2 are verified.

## Constraints

- Work locally on `ml-upgrade`; do not pull, push, merge, or rebase.
- Preserve `backend/static/tailwind.css` in its current state. The earlier frontend
  check rewrote this pre-existing untracked file; report that side effect.
- Treat the current worktree as user work. Integrate changes surgically and do not
  overwrite or silently discard them.
- Maintain additive/backward-compatible API behavior, except the explicitly
  requested non-2xx health response when the database is unavailable.
- Pin SHAP and retain exact scikit-learn/xgboost requirements; record training
  versions in artifact metadata and reject incompatible artifacts clearly.
- Run backend tests and frontend syntax/build checks after each implementation
  tier; report failures and do not claim unrun checks passed.
- Commit only scoped, verified changes at tier boundaries; do not include local
  database sidecars or unrelated worktree files.
- The repository documents deployment as local Python, Docker with a durable
  `/data` volume, or an optional container PaaS. No BESCOM identity provider or
  real AMI evaluation corpus is configured. Rollback commands can be documented,
  but must be marked BLOCKED until verified with a working Docker daemon.

## Approaches

1. **Incremental tiered closure (selected):** inspect existing changes, preserve
   contracts and architecture, and implement/verify Tier 1, then Tier 2, then
   Tier 3. This follows the requested priority and limits regression risk.
2. **Broad rewrite:** replace or reorganize frontend/backend/test architecture.
   Rejected because it expands scope and endangers existing work and API behavior.
3. **Evidence-only report:** document the baseline without changes. Rejected
   because the request explicitly requires closing the gaps.

## Design and acceptance criteria

### Tier 1

- Run Playwright against the real FastAPI app for login, each vendor sample,
  validation/findings, source-to-target transform, history, and HTML report at
  1440px and 360px. Capture browser console errors and screenshots on failure.
- Audit Alpha, Beta, Gamma, and Delta abnormal samples. Each injected fault must
  be detected, and round-trips must preserve energy and timestamps; fix misses
  with regression tests. Use the checked-in `samples/` files as the sample
  corpus, including the Alpha tamper and Beta anomaly inputs, and the existing
  simulator's explicit anomaly/tamper injection options. Extend, rather than
  replace, the directed cross-vendor semantic tests.
- Preserve synthetic-data labeling in API/UI. Explanations report exactly
  `shap` or `feature_importance_fallback`; real evaluation reports include anomaly
  precision, recall, and alert volume by threshold. Compute the view from a real
  holdout evaluation run on the checked-in SYNTHETIC data; do not hand-edit
  `metrics.json`.
- Read sklearn/xgboost training versions only from saved artifact evidence. If a
  version cannot be proven from the artifact, record it as `unknown`; never infer
  it from the current environment. Fail clearly on a proven mismatch and include
  an artifact-load smoke test.
- Make `/health` return 503 with a non-`ok` status when DB access fails; add
  `/health/live` and `/health/ready`. Keep `/health`'s existing JSON keys
  (`status`, `version`, `db`), reporting `status: error` and `db: error` on 503.
  Keep `/ready` working as a compatible readiness alias and do not change
  `/api/health`. The only in-repository client asserting the old 200-on-DB-failure
  behavior is `test_service_health_reports_database_error`; update that test
  deliberately.
- Fix VY-01, VY-02, VY-04–07, and VY-10 with focused Playwright coverage. The
  tab bar must avoid overlap/clipping/page overflow at 320, 360, 375, 390, 430,
  and 768px; the modal must manage focus, Escape, and trigger restoration; tabs
  must implement Left/Right wrapping and Home/End with roving tabindex and the
  complete tab/tabpanel ARIA relationships.

### Tier 2

- Verify role-based access with tests that hit each protected endpoint as each
  role (including unauthenticated access) and assert both allowed and denied
  behavior. Use the existing `admin`, `operator`, and `viewer` roles as the
  initial hypothesis: viewer reads statistics/catalog/saved runs/reports/suites/
  meter profiles; operator executes workbench/ML/suite workflows but cannot
  administer users; admin can do both. The matrix is not considered verified
  until the endpoint-by-role tests pass. The guided demo uses real backend calls.
- Fix VY-11 with actual contrast calculations for all text/background pairs in
  `start.html`, `dashboard.html`, and `index.html`; preserve before/after tables
  from the calculation. Add the VY-12 skip link.
- Unify design tokens across the three pages without a visual rewrite.
- Extend the existing CI workflow rather than replacing it. Add pytest markers,
  coverage configuration, and test-architecture documentation. Preserve the
  existing non-root container user, use `$PORT` with an 8000 default, probe
  `/health/ready`, and configure documented Compose CPU/memory guardrails; have
  CI build the image and smoke-test its health endpoint.

### Tier 3

- Only after Tier 1 and 2 are verified, add a measured basic load test, release
  manifest, rollback documentation, SRE docs, and drift monitoring. Document
  backup/restore and rollback commands for a versioned Docker image and durable
  SQLite volume, but mark those commands **BLOCKED (Docker daemon unavailable)**;
  do not claim they work until run against Docker. Drift reporting must
  distinguish synthetic evidence from observed live readings; do not claim
  real-data calibration without such data.
- Add structured JSON request logs containing request ID, route, status, and
  duration but no payloads or credentials; expose measured request metrics with
  documented single-process scope. Add a SQLite backup/restore test against a
  temporary database and SRE runbooks for health, logging, metrics, and recovery.
- If an item cannot be run or safely completed, record it as unexecuted with
  evidence and place it in README Roadmap / Known Limitations.

## Builder calls

- Keep the implementation ordered by the user's tiers and run checks at each
  boundary.
- Use the existing Playwright setup if it can cover the requested flow; extend
  `tests/browser` or place the workflow under `tests/e2e`.
- Keep Docker validation blocked until the daemon can be reached; still implement
  the Dockerfile/CI changes and validate all non-Docker portions locally.
- Generate ML documentation from real training output rather than editing
  artifact metrics by hand.

## Builder-check questions and resolutions

1. **What role/permission matrix is authoritative?** Resolve it through tests
   that exercise each protected endpoint as every role rather than copying the
   prose matrix. Evidence: roles/authorization in `backend/security/auth.py`,
   route guards in `backend/api/routes.py` and `backend/api/ml_routes.py`,
   partial existing coverage in `tests/test_auth.py`, and the current hypothesis
   in `docs/SECURITY_AND_ACCESS.md`.
2. **What deployment and rollback target applies?** The repository supports
   local Python, Docker with `/data`, and optional container PaaS. Use the
   versioned Docker image and durable SQLite volume for rollback documentation;
   mark commands BLOCKED until Docker is reachable. Evidence: `DEPLOYMENT.md`,
   `Dockerfile`, and `docker-compose.yml`; baseline `docker version` could not
   connect to `dockerDesktopLinuxEngine`.
3. **What artifact metadata contract should version checks use?** Inspect and
   trust only versions proven from saved artifacts; write `unknown` otherwise.
   Evidence: `app/ml/artifacts/`, `app/ml/artifacts/feature_schema.json`,
   `app/ml/inference.py`, and artifact export in `ml_training/train.py`.
4. **What health behavior remains compatible?** Preserve the healthy `/health`
   JSON keys, keep `/ready`, and leave `/api/health` unchanged; intentionally
   change only `/health`'s DB-failure HTTP status and `status` value. Evidence:
   `backend/main.py`, the `/api/health` route in `backend/api/routes.py`, and
   `test_service_health_reports_database_error` in `tests/test_api_and_engine.py`.
5. **Which sample/anomaly inputs define acceptance?** Use checked-in samples
   plus the simulator's explicit anomaly/tamper injection paths; retain the
   directed semantic round-trip suite. Evidence: `samples/`,
   `backend/generator/simulator.py`, `tests/test_adapters.py`, and
   `tests/test_roundtrip_directed.py`.
