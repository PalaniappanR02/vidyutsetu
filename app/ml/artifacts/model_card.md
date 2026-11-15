# VIDYUTSETU Model Card

- **Training data:** SYNTHETIC AMI payloads only.
- **Purpose:** Pre-integration payload fault classification and anomaly detection.
- **Selected fault classifier:** xgboost.
- **Synthetic test accuracy:** 0.9705.
- **Synthetic test macro-F1:** 0.9507.
- **Anomaly detection precision:** 0.3103.
- **Anomaly detection recall:** 0.9730.
- **Anomaly detection F1:** 0.4706.
- **Anomaly detection ROC-AUC:** 0.9600.

These results are measured on a synthetic, meter-disjoint holdout. They do not establish real-world utility or BESCOM performance.
