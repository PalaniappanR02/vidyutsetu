# ML Engineering and Model Operations

## Data and decision boundaries

All training examples and generated AMI telemetry are **SYNTHETIC**. The fault
classifier and anomaly detector are screening aids; deterministic schema,
semantic, and physical validation rules remain the source of conformance scores.
Do not treat model output as a confirmed fault or as a substitute for utility
engineering review.

## Supported training workflow

`ml_training/train.py` is the supported trainer. `ml_training/untitled5.py` is
an archived notebook export retained for historical reference; do not use it to
generate runtime artifacts. Generate synthetic labeled data with
`ml_training/generate_data.py`, then pass the resulting CSV to the trainer:

```powershell
python -m ml_training.generate_data
python -m ml_training.train --data-csv data/ami_payload_dataset_synthetic.csv --output-dir app/ml/artifacts
```

The trainer rejects rows not marked synthetic, uses grouped splits to keep
records from a meter together across train and evaluation data, and writes the
models, feature schema, metrics, and model card as one artifact bundle. Use a
fixed seed for reproducibility. Review the saved test metrics before promoting
any artifact bundle.

`app/ml/inference.py` loads artifact metadata at runtime. `metrics.json` is the
source of truth for reported model metrics and the anomaly threshold; code and
the UI must not duplicate those values. Pickled model classes must remain
defined in importable modules, not in `__main__`.

## Artifact changes and limitations

Promote the complete artifact bundle together; do not replace a model file
without its matching `feature_schema.json` and `metrics.json`. The runtime
checks required files and the saved classifier's transformed feature names.
Model loading uses joblib and therefore assumes artifacts are trusted files
from the project's controlled training process. Artifact signature verification,
automated model promotion, drift-based retraining, and production monitoring
are not currently implemented.
