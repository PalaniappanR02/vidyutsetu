ROLE: Senior full-stack + ML engineer. Continue my existing VidyutSetu project
(AMI interoperability and conformance workbench: FastAPI + SQLite + sklearn,
static frontend in backend/static). Do NOT rebuild it. Work on branch
ml-upgrade. Windows + PowerShell; use .\.venv\Scripts\python.exe for Python.

HOW WE WORK
Do one phase at a time. At the end of each phase, print the phase report and
STOP until I say "continue". If you lose context, re-read this file and run
git log --oneline -10 to see where we are.

HARD RULES
- Never push, merge, force-push or delete branches. Local commits and tags
  only, one per phase.
- Never retrain models. Never modify app/ml/artifacts or model files. Do not
  run ml_training/train.py.
- Additive changes only: no removed features, no changed response shapes, no
  duplicate endpoints or tables (look for existing ones first). Preserve
  existing DB records.
- Reuse existing models, services, adapters, validators and routes.
- No fake ML output and no hardcoded analytics. Label rule-based results
  "rule" and learned results "ml". All training data is SYNTHETIC; say so in
  the UI. Standards rules stay authoritative; ML only screens for what rules
  miss. Never claim the tool certifies compliance.
- Never commit secrets. If .env, .env.local, .env.staging or .env.production
  are tracked, run git rm --cached on them, add them to .gitignore, and tell
  me which keys to rotate.
- Do not claim anything works unless you ran it in this session and can show
  the output. Never invent test counts, metrics or screenshots.
- Challenge each feature first (business problem, approach, data, validation).
  If you cannot justify or demonstrate it, skip it and say why.
- Existing tests must keep passing.

PROOF AT EVERY PHASE
For each check, show the exact command and the last 5-15 lines of real output.
If a check fails, find the root cause, fix it, rerun, and show both runs. End
each phase with a table: Built / Prototype / Not done, and a line listing the
skills you actually applied and what each one changed or caught.

SKILLS
Setup (before Phase 0): list the skills Kiro can see (also check
~/.kiro/skills, ~/.agents/skills and ~/.claude/skills) and confirm each skill
below has a SKILL.md. Print found and missing names. Use a skill through its
slash command if Kiro supports it (for example /frontend-design); if the slash
command is not available, read that skill's SKILL.md from disk and follow it.
Never pretend to have used a skill. Do not copy, move or overwrite anything
inside the skills folders.
- Phase 0: code-improver and modern-python, READ-ONLY review. Do not refactor.
- Phase 1 and 2: test-driven-development (write each test first, show it
  fail, then pass), modern-python (typing, Pydantic v2 model_dump instead of
  .dict(), timezone-aware datetimes, no deprecated calls in new code).
- Phase 3: frontend-design, then accessibility if installed, then
  webapp-testing to drive the real pages in a headless browser.
- Phase 4: spec-driven-development (write a short spec per feature before
  coding; implement only to the spec).
- Phase 5: modern-python for logging and validation code;
  cloud-solution-architect as a read-only review of Dockerfile, Render and
  Postgres settings (recommend only; apply only additive changes I approve).
- Phase T: verification-before-completion, webapp-testing, and code-improver
  (read-only).
- Any error at any time: systematic-debugging (find root cause, change one
  thing, rerun).
- Do NOT use brainstorming or planning skills (the plan is set), supabase
  (we use SQLite; Postgres only via DATABASE_URL), or
  subagent-driven-development for edits. Read-only subagents are fine; only
  one agent edits files.

PHASE 0 - AUDIT (no code changes)
Run git status, git log --oneline -15 and git tag --list. Read
backend/main.py, backend/api/routes.py, backend/db/database.py,
app/ml/inference.py, app/ml/preprocessing.py, requirements.txt and tests/.
Report which of these already exist and work (check by reading the code AND
by calling the endpoint on a local server): meter_history table, the
`stages` field in /api/workbench/execute, /api/compare, /api/roundtrip,
/api/suites and suite_runs, landing page at /, dashboard at /dashboard. List
bugs, dummy or hardcoded logic, tracked secrets, and tests that assume the
dashboard is served at "/". Run the baseline once:
.\.venv\Scripts\python.exe -m pytest tests -q 2>&1 | Select-Object -Last 15
Give me a plan of only what is missing. STOP.

PHASE 1 - BACKEND (skip anything Phase 0 found complete)
1. meter_history(meter_id, ts, payload_json): keep the last 50 readings per
   meter. /ml/validate and /ml/validate-batch prepend stored history in
   ARRIVAL ORDER (never sort by timestamp), score only the new readings, then
   append them. Omitted keys count as null.
2. Five stages (parse, syntactic, semantic mapping, physical sanity, ML
   screening) as an extra `stages` field in /api/workbench/execute:
   {name, status pass|warn|fail|skipped, duration_ms, diagnostics[],
   root_cause, suggested_action}. Existing score and issues unchanged.
3. POST /api/compare {baseline_run_id, candidate_run_id}: resolved,
   persistent, newly_introduced failures plus score deltas.
4. POST /api/roundtrip {vendor_a, vendor_b, payload}: A -> canonical -> B ->
   canonical with a field-level diff.
5. test_suites and suite_runs tables; POST /api/suites, POST
   /api/suites/{id}/run, GET /api/suites, reusing the existing execute path.
6. Add a model version tag and a data-quality score to each run result
   (additive fields; read the version from existing metrics or artifact
   metadata, do not retrain).
Tests: unit, API and edge cases for each item, using an isolated in-memory or
temp SQLite per test so history never leaks between tests. Update the earlier
ML regression test so stored history cannot change its result. Keep the
Phase 5 regression test (held-out meters in CSV order, each class recall
within 3 points of metrics.json).
Proof: full pytest (all pass), plus a live smoke test: start uvicorn on port
8765, call each new endpoint with a real payload, paste the responses, stop
the server. Commit "Batch A", tag batch-a. STOP.

PHASE 2 - ML AND ANALYTICS (only what is real)
Each finding gets severity, confidence, a short explanation and a source tag
(rule|ml). Add drift monitoring and meter behaviour profiling only if they
compute from stored history and are tested; otherwise mark Roadmap and skip.
SHAP only if it runs cleanly on the existing model without retraining; else
skip. Add an exportable conformance report (HTML or PDF) built from a real
run. Proof: pytest for new code, the path of a sample export, and the metrics
quoted from metrics.json (read them, do not recompute or invent). Commit
"Batch B", tag batch-b. STOP.

PHASE 3 - FRONTEND
Landing page is at / and dashboard at /dashboard (done in Phase F; do not
touch backend/static/_next). Logo: use backend/static/assets/logo.png and
favicon.png if present; if missing, tell me and continue without inventing
one. Palette: navy #0B2545, teal #0E9AA7, cyan #19C2D0, amber #F59E0B (accent
only: main call-to-action and key numbers), background #F4F8FB. Warnings and
ML anomalies use amber, never green. On the dashboard (keep layout, cards and
tables):
- Retheme with CSS variables, green -> teal.
- Header: logo, one-word nav labels, short subtitle, and change
  "IEC 61968-9 Conforming" to "IEC 61968-9 aligned".
- Empty stats show 0 plus a hint, never "--".
- "ML Fault Screening" card from GET /ml/health with headline metrics and a
  "Trained on synthetic data" badge.
- "ML Verdict" panel on results from ml_findings with rule/ml tags and
  loading, error and empty states.
- Pipeline stage view from `stages`, run comparison view, round-trip diff
  view, suites list/run, anomaly heatmap from real run data, vendor mapping
  matrix, side-by-side contract diff, report export.
- A link back to the landing page. Light/dark toggle only if it works
  without breaking the design.
The landing preview stays labelled illustrative; never show fabricated numbers
as live data. WCAG AA contrast, visible focus, prefers-reduced-motion.
Proof: start the server and HTTP-check /, /dashboard, /docs, every static
asset URL used by both pages (all 200) and every API call the dashboard makes.
With webapp-testing or Playwright, click each dashboard tab and the buttons
above, report console errors and save screenshots (give the paths). If browser
testing is impossible, say so and list the manual clicks I must do. Commit
"Batch C", tag batch-c. STOP.

PHASE 4 - DIFFERENTIATORS (at most two, each with a real demo)
Candidates: schema mapping suggestions (engineer approves each), self-
generating test scenarios from vendor schemas (engineer approves, then runs),
cyber indicators labelled "indicators, not confirmed attacks". Skip the
digital twin unless time remains. Write the spec first, then tests, then code,
then a live demo response. Commit "Batch D", tag batch-d. STOP.

PHASE 5 - PRODUCTION BASICS
Input validation and upload size limits, structured logging, DATABASE_URL
Postgres option (SQLite stays default), Dockerfile check, /api/health, secrets
cleanup. Update README, USER_GUIDE and KNOWN_LIMITATIONS to say what is truly
built, including: the fault classifier needs reading history, data is
synthetic, and the tool does not certify compliance. Fix the README clone URL
and add a LICENSE file if the badge references one. Commit "Batch E", tag
batch-e. STOP.

PHASE T - FINAL VERIFICATION
1. Full pytest; paste the summary line.
2. Fix any test that assumed the dashboard is at "/" so it targets /dashboard,
   and add an assertion that "/" serves the landing page.
3. Cold-start the server and repeat the HTTP, asset and endpoint checks, plus
   the browser pass.
4. verification-before-completion: list every claim you will make and the
   command output that proves it.
5. Final report: Built / Prototype / Not done / Roadmap, files changed, test
   counts, and manual steps left for me (logo, pushing, Render redeploy,
   rotating secrets). Tag phase-t-done. Do not push.