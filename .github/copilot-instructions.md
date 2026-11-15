Project: VIDYUTSETU, a pre-integration testing workbench for AMI data exchange

(HES to MDMS payload validation). POWER HACK 2026 (BESCOM), team ACHIEVERS.

Stack: FastAPI, Pydantic v2, SQLite, Pytest; React + TypeScript frontend.

Palette: ivory background, forest green primary, terracotta accent.



Rules:

\- Never hardcode metrics anywhere. Always read them from metrics.json.

\- Training data is SYNTHETIC. Label it as such in code, docs and the UI.

\- ML code lives in app/ml/. Training code lives in ml\_training/.

\- Any class used inside a pickled model must be importable from a real module,

&#x20; never defined in \_\_main\_\_.

\- Keep API response shapes backward compatible. Add tests for every change.

\- Run pytest and the type-check/build after every edit. If a command fails,

&#x20; report it. Never guess or invent results.

\- Explain each change briefly. Ask before deleting files or changing public

&#x20; API contracts.

\- Pin exact scikit-learn and xgboost versions in requirements.txt.

