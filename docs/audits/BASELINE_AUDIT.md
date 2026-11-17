# Baseline Audit

## Scope
This baseline audit covers the VidyutSetu repository as it exists in the current workspace, including the FastAPI backend, the SQLite-backed validation engine, the static frontend, the ML artifact bundle under `app/ml/`, and the training utilities in `ml_training/`.

## Repository snapshot
- Architecture: FastAPI + Pydantic v2 + SQLite + sklearn/xgboost-based ML screening
- Data handling: synthetic AMI telemetry, vendor-specific adapters, canonical normalization and scoring
- Frontend: static workbench served from `backend/static/` with a dashboard and landing view
- Governance: artifact-driven ML health, environment-based configuration, and synthetic-data labeling

## Baseline verification
Command run:

```powershell
pytest -q
```

Observed result in this environment:
- 119 passed
- 4 skipped
- 0 failed
- warnings only from NumPy joblib pickle compatibility on the current NumPy version

This means the current branch has no reproduced P0/P1 runtime regression under the repo's automated checks in the active workspace.

## Key findings
### 1. Core app is stable
The repository bootstraps successfully, exposes the API, and keeps the validation/reporting pipeline functioning without a reproduced critical defect in the current checkout.

### 2. ML artifacts are metadata-driven
The runtime reads model metadata and metrics from `app/ml/artifacts/metrics.json` and `app/ml/artifacts/feature_schema.json` instead of hard-coding values in Python. This keeps the health checks and UI aligned with the trained artifact bundle.

### 3. Synthetic data is labeled and documented
The training data and inference metadata explicitly mark the model as synthetic. This is reflected in code paths, docs, and the UI text so generated data is not misrepresented as production telemetry.

### 4. Canonical training path is explicit
The supported training flow is centered in `ml_training/train.py`, while the notebook-style export remains archival rather than the authoritative path.

## Risks and follow-ups
- The repository still depends on careful artifact provenance when retraining or replacing ML bundles.
- Any future model retraining must keep the synthetic marker, schema contract, and `metrics.json` bundle in sync.
- Operational hardening (deployment secrets, monitoring, and staged rollout controls) remains a deployment concern rather than a current code defect.

## Baseline status
Status: stable for the current branch under automated verification.

No direct production blocker was reproduced during this audit. The active repository is suitable for controlled iteration and feature refinement, with the primary focus remaining on maintaining artifact integrity and deployment hygiene.
