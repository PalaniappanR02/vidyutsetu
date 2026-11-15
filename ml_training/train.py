"""Train VIDYUTSETU models from a labeled SYNTHETIC AMI CSV."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml.preprocessing import AMIPayloadPreprocessor

LOGGER = logging.getLogger("vidyutsetu.ml.training")
SEED = 42
FAULT_LABEL = "fault_label"
ANOMALY_LABEL = "is_anomaly_label"
METER_ID = "meter_id"
NON_FEATURE_COLUMNS = (FAULT_LABEL, ANOMALY_LABEL, "anomaly_type")
ARTIFACT_NAMES = {
    "classifier": "fault_classifier.joblib",
    "detector": "anomaly_detector.joblib",
    "label_encoder": "label_encoder.joblib",
    "feature_schema": "feature_schema.json",
    "metrics": "metrics.json",
    "model_card": "model_card.md",
    "shap": "shap_summary.json",
}


def load_training_data(csv_path: Path) -> pd.DataFrame:
    """Load a labeled synthetic CSV and reject incomplete or incompatible data."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Training CSV does not exist: {csv_path}")

    data = pd.read_csv(csv_path)
    required = {METER_ID, FAULT_LABEL, ANOMALY_LABEL}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Training CSV is missing required columns: {', '.join(missing)}")
    if data.empty:
        raise ValueError("Training CSV contains no rows")
    if data[METER_ID].isna().any() or data[METER_ID].astype(str).str.strip().eq("").any():
        raise ValueError("Training CSV must have a non-empty meter_id on every row")
    if data[FAULT_LABEL].isna().any():
        raise ValueError("Training CSV must have a fault_label on every row")
    if data[ANOMALY_LABEL].isna().any():
        raise ValueError("Training CSV must have an is_anomaly_label on every row")

    numeric_anomaly_labels = pd.to_numeric(data[ANOMALY_LABEL], errors="coerce")
    anomaly_labels = set(numeric_anomaly_labels.dropna().unique())
    if numeric_anomaly_labels.isna().any() or not anomaly_labels.issubset({0, 1}):
        raise ValueError("is_anomaly_label must contain only 0 or 1")
    data[ANOMALY_LABEL] = numeric_anomaly_labels.astype(int)

    if "is_synthetic" in data.columns:
        synthetic_flags = set(pd.to_numeric(data["is_synthetic"], errors="coerce").dropna().unique())
        if data["is_synthetic"].isna().any() or synthetic_flags != {1}:
            raise ValueError("Training CSV must contain only SYNTHETIC rows (is_synthetic=1)")

    if data[FAULT_LABEL].nunique() < 2:
        raise ValueError("Training CSV must contain at least two fault classes")
    if data[METER_ID].nunique() < 2:
        raise ValueError("Training CSV must contain at least two distinct meters")
    if data[ANOMALY_LABEL].nunique() < 2:
        raise ValueError("Training CSV must contain both normal and anomalous rows")

    return data.reset_index(drop=True)


def _grouped_holdout(
    data: pd.DataFrame, encoded_labels: np.ndarray, test_size: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Choose a meter-disjoint holdout containing each fault class on both sides."""
    from sklearn.model_selection import GroupShuffleSplit

    splitter = GroupShuffleSplit(n_splits=100, test_size=test_size, random_state=seed)
    all_classes = set(np.unique(encoded_labels))
    for train_indices, test_indices in splitter.split(
        data, encoded_labels, groups=data[METER_ID].astype(str)
    ):
        if (
            set(np.unique(encoded_labels[train_indices])) == all_classes
            and set(np.unique(encoded_labels[test_indices])) == all_classes
        ):
            return train_indices, test_indices
    raise ValueError(
        "Could not create a meter-disjoint holdout containing every fault class; "
        "add more meters per class or adjust the input data"
    )


def _pipeline(classifier: Any, *, scale: bool = False) -> Pipeline:
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    steps: list[tuple[str, Any]] = [("preprocessor", AMIPayloadPreprocessor())]
    if scale:
        steps.append(("scaler", StandardScaler()))
    steps.append(("classifier", classifier))
    return Pipeline(steps)


def _cross_validate_model(
    estimator: Pipeline,
    records: pd.DataFrame,
    labels: np.ndarray,
    folds: GroupKFold,
    groups: np.ndarray,
    *,
    weighted_fit: bool = False,
) -> dict[str, float]:
    from sklearn.base import clone
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.utils.class_weight import compute_sample_weight

    accuracy_scores: list[float] = []
    macro_f1_scores: list[float] = []

    for train_indices, validation_indices in folds.split(records, labels, groups):
        fold_estimator = clone(estimator)
        fit_params = {}
        if weighted_fit:
            fit_params["classifier__sample_weight"] = compute_sample_weight(
                class_weight="balanced", y=labels[train_indices]
            )
        fold_estimator.fit(records.iloc[train_indices], labels[train_indices], **fit_params)
        predictions = fold_estimator.predict(records.iloc[validation_indices])
        accuracy_scores.append(accuracy_score(labels[validation_indices], predictions))
        macro_f1_scores.append(
            f1_score(labels[validation_indices], predictions, average="macro", zero_division=0)
        )

    return {
        "accuracy_mean": float(np.mean(accuracy_scores)),
        "accuracy_std": float(np.std(accuracy_scores)),
        "macro_f1_mean": float(np.mean(macro_f1_scores)),
        "macro_f1_std": float(np.std(macro_f1_scores)),
    }


def _valid_normal_records(data: pd.DataFrame) -> pd.DataFrame:
    normal_rows = data.loc[
        data[FAULT_LABEL].astype(str).eq("VALID") & data[ANOMALY_LABEL].eq(0)
    ]
    return normal_rows.drop(columns=list(NON_FEATURE_COLUMNS), errors="ignore")


def _grouped_anomaly_holdout(data: pd.DataFrame, seed: int) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.model_selection import GroupShuffleSplit

    labels = data[ANOMALY_LABEL].to_numpy(dtype=int)
    groups = data[METER_ID].astype(str).to_numpy()
    splitter = GroupShuffleSplit(n_splits=100, test_size=0.2, random_state=seed)
    for train_indices, validation_indices in splitter.split(data, labels, groups):
        if (
            set(np.unique(labels[validation_indices])) == {0, 1}
            and not _valid_normal_records(data.iloc[train_indices]).empty
        ):
            return train_indices, validation_indices
    raise ValueError(
        "Could not create a meter-disjoint anomaly validation split containing both "
        "normal and anomalous rows; add more meters or adjust the input data"
    )


def _anomaly_detector(seed: int, quick: bool) -> Pipeline:
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import IsolationForest
    from sklearn.pipeline import Pipeline

    selected_features = ("kwh_delta", "voltage_clean", "kwh_rolling_zscore")
    feature_indices = [
        AMIPayloadPreprocessor.feature_names.index(name) for name in selected_features
    ]
    return Pipeline(
        [
            ("preprocessor", AMIPayloadPreprocessor()),
            (
                "consumption_features",
                ColumnTransformer(
                    [("selected", "passthrough", feature_indices)],
                    remainder="drop",
                    verbose_feature_names_out=False,
                ),
            ),
            (
                "detector",
                IsolationForest(
                    contamination="auto", random_state=seed, n_jobs=-1 if quick else 1
                ),
            ),
        ]
    )


def _select_anomaly_threshold(scores: np.ndarray, labels: np.ndarray) -> float:
    from sklearn.metrics import f1_score

    if scores.size == 0 or scores.shape != labels.shape:
        raise ValueError("Anomaly scores and labels must be non-empty arrays of equal shape")
    thresholds = np.unique(scores)
    return float(
        max(
            thresholds,
            key=lambda threshold: (
                f1_score(labels, scores >= threshold, zero_division=0),
                threshold,
            ),
        )
    )


def _classification_metrics(
    estimator: Pipeline,
    records: pd.DataFrame,
    labels: np.ndarray,
    class_names: list[str],
) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    predictions = estimator.predict(records)
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "classification_report": classification_report(
            labels,
            predictions,
            labels=np.arange(len(class_names)),
            target_names=class_names,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(
            labels, predictions, labels=np.arange(len(class_names))
        ).tolist(),
    }


def _feature_importance(estimator: Pipeline) -> dict[str, float]:
    classifier = estimator.named_steps["classifier"]
    feature_names = estimator.named_steps["preprocessor"].get_feature_names_out()
    if hasattr(classifier, "feature_importances_"):
        importances = np.asarray(classifier.feature_importances_, dtype=float)
    elif hasattr(classifier, "coef_"):
        importances = np.mean(np.abs(classifier.coef_), axis=0)
    else:
        return {}
    return {
        str(name): float(importance)
        for name, importance in sorted(
            zip(feature_names, importances), key=lambda item: item[1], reverse=True
        )
    }


def _shap_summary(
    estimator: Pipeline, records: pd.DataFrame, output_path: Path
) -> dict[str, Any]:
    try:
        import shap
    except ModuleNotFoundError as error:
        result = {
            "status": "unavailable",
            "reason": "Install the optional 'shap' package to calculate SHAP values.",
        }
        LOGGER.warning("%s", result["reason"])
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    feature_matrix = estimator.named_steps["preprocessor"].transform(records)
    classifier = estimator.named_steps["classifier"]
    sample_count = min(len(feature_matrix), 200)
    explanation = shap.Explainer(classifier, feature_matrix[:sample_count])(
        feature_matrix[:sample_count]
    )
    values = np.asarray(explanation.values)
    if values.ndim == 3:
        values = np.mean(np.abs(values), axis=(0, 2))
    else:
        values = np.mean(np.abs(values), axis=0)
    feature_names = estimator.named_steps["preprocessor"].get_feature_names_out()
    result = {
        "status": "complete",
        "mean_absolute_shap_values": {
            str(name): float(value)
            for name, value in sorted(
                zip(feature_names, values), key=lambda item: item[1], reverse=True
            )
        },
    }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _model_card(metrics: dict[str, Any]) -> str:
    selected = metrics["selected_classifier"]
    test_metrics = metrics["fault_classification"]["test"][selected]
    anomaly = metrics["anomaly_detection"]["test"]
    return "\n".join(
        [
            "# VIDYUTSETU Model Card",
            "",
            "- **Training data:** SYNTHETIC AMI payloads only.",
            "- **Purpose:** Pre-integration payload fault classification and anomaly detection.",
            f"- **Selected fault classifier:** {selected}.",
            f"- **Synthetic test accuracy:** {test_metrics['accuracy']:.4f}.",
            f"- **Synthetic test macro-F1:** {test_metrics['macro_f1']:.4f}.",
            f"- **Anomaly detection precision:** {anomaly['precision']:.4f}.",
            f"- **Anomaly detection recall:** {anomaly['recall']:.4f}.",
            f"- **Anomaly detection F1:** {anomaly['f1']:.4f}.",
            f"- **Anomaly detection ROC-AUC:** {anomaly['roc_auc']:.4f}.",
            "",
            "These results are measured on a synthetic, meter-disjoint holdout. They do not "
            "establish real-world utility or BESCOM performance.",
            "",
        ]
    )


def train(
    data: pd.DataFrame, output_dir: Path, seed: int = SEED, quick: bool = False
) -> dict[str, Any]:
    """Fit, evaluate, and export classifier and anomaly detector artifacts."""
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import GroupKFold, RandomizedSearchCV
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight

    output_dir.mkdir(parents=True, exist_ok=True)
    cv_splits = 3 if quick else 5
    if data[METER_ID].nunique() < cv_splits:
        raise ValueError(f"At least {cv_splits} distinct meters are required for GroupKFold")
    encoder = LabelEncoder()
    encoded_labels = encoder.fit_transform(data[FAULT_LABEL].astype(str))
    train_indices, test_indices = _grouped_holdout(data, encoded_labels, 0.2, seed)
    train_data = data.iloc[train_indices]
    test_data = data.iloc[test_indices]
    train_records = train_data.drop(columns=list(NON_FEATURE_COLUMNS), errors="ignore")
    test_records = test_data.drop(columns=list(NON_FEATURE_COLUMNS), errors="ignore")
    y_train = encoded_labels[train_indices]
    y_test = encoded_labels[test_indices]
    class_names = [str(name) for name in encoder.classes_]
    cv_groups = train_data[METER_ID].astype(str).to_numpy()
    if len(np.unique(cv_groups)) < cv_splits:
        raise ValueError(
            "The meter-disjoint training split needs at least "
            f"{cv_splits} distinct meters for GroupKFold"
        )
    folds = GroupKFold(n_splits=cv_splits)

    from xgboost import XGBClassifier

    candidates = {
        "logistic_regression": _pipeline(
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed),
            scale=True,
        ),
        "random_forest": _pipeline(
            RandomForestClassifier(
                class_weight="balanced_subsample",
                n_estimators=300,
                random_state=seed,
                n_jobs=-1 if quick else 1,
            )
        ),
        "xgboost": _pipeline(
            XGBClassifier(
                objective="multi:softprob",
                eval_metric="mlogloss",
                random_state=seed,
                n_jobs=1,
                tree_method="hist",
                **({"n_estimators": 150} if quick else {}),
            )
        ),
    }

    cv_results: dict[str, Any] = {}
    for name, estimator in candidates.items():
        if quick:
            print(f"Training {name} with {cv_splits}-fold cross-validation...", flush=True)
        cv_results[name] = _cross_validate_model(
            estimator,
            train_records,
            y_train,
            folds,
            cv_groups,
            weighted_fit=name == "xgboost",
        )

    xgb_search = RandomizedSearchCV(
        estimator=candidates["xgboost"],
        param_distributions={
            "classifier__n_estimators": [100, 150] if quick else [100, 200, 300],
            "classifier__max_depth": [3, 5, 7],
            "classifier__learning_rate": [0.03, 0.1, 0.2],
            "classifier__subsample": [0.8, 1.0],
            "classifier__colsample_bytree": [0.8, 1.0],
        },
        n_iter=4 if quick else 10,
        scoring="f1_macro",
        cv=folds,
        random_state=seed,
        n_jobs=-1 if quick else 1,
        refit=True,
        error_score="raise",
    )
    if quick:
        print("Training xgboost with randomized search...", flush=True)
    xgb_search.fit(
        train_records,
        y_train,
        groups=cv_groups,
        classifier__sample_weight=compute_sample_weight("balanced", y_train),
    )
    best_xgb = xgb_search.best_estimator_
    cv_results["xgboost"]["randomized_search_best_macro_f1"] = float(xgb_search.best_score_)
    cv_results["xgboost"]["randomized_search_best_params"] = xgb_search.best_params_
    candidates["xgboost"] = best_xgb

    test_results: dict[str, Any] = {}
    for name, estimator in candidates.items():
        if name != "xgboost":
            estimator.fit(train_records, y_train)
        test_results[name] = _classification_metrics(
            estimator, test_records, y_test, class_names
        )

    selected_name = max(
        candidates,
        key=lambda name: cv_results[name].get(
            "randomized_search_best_macro_f1", cv_results[name]["macro_f1_mean"]
        ),
    )
    selected_classifier = candidates[selected_name]

    anomaly_train_indices, anomaly_validation_indices = _grouped_anomaly_holdout(
        train_data, seed
    )
    calibration_records = _valid_normal_records(train_data.iloc[anomaly_train_indices])
    validation_data = train_data.iloc[anomaly_validation_indices]
    validation_records = validation_data.drop(
        columns=list(NON_FEATURE_COLUMNS), errors="ignore"
    )
    validation_labels = validation_data[ANOMALY_LABEL].to_numpy(dtype=int)
    calibration_detector = _anomaly_detector(seed, quick)
    if quick:
        print("Calibrating anomaly detector threshold...", flush=True)
    calibration_detector.fit(calibration_records)
    validation_scores = -calibration_detector.decision_function(validation_records)
    anomaly_threshold = _select_anomaly_threshold(validation_scores, validation_labels)

    normal_records = _valid_normal_records(train_data)
    if normal_records.empty:
        raise ValueError("Training split has no valid normal rows for Isolation Forest fitting")
    detector = _anomaly_detector(seed, quick)
    if quick:
        print("Training anomaly detector...", flush=True)
    detector.fit(normal_records)
    anomaly_scores = -detector.decision_function(test_records)
    anomaly_predictions = (anomaly_scores >= anomaly_threshold).astype(int)
    anomaly_truth = test_data[ANOMALY_LABEL].to_numpy(dtype=int)
    if len(np.unique(anomaly_truth)) != 2:
        raise ValueError("Meter-disjoint test split must contain normal and anomalous rows")
    anomaly_metrics = {
        "precision": float(precision_score(anomaly_truth, anomaly_predictions, zero_division=0)),
        "recall": float(recall_score(anomaly_truth, anomaly_predictions, zero_division=0)),
        "f1": float(f1_score(anomaly_truth, anomaly_predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(anomaly_truth, anomaly_scores)),
        "threshold": anomaly_threshold,
        "validation_f1": float(
            f1_score(
                validation_labels,
                validation_scores >= anomaly_threshold,
                zero_division=0,
            )
        ),
    }

    robustness_records = test_records.copy()
    if "voltage" in robustness_records:
        robustness_records["voltage"] = None
        robustness_predictions = selected_classifier.predict(robustness_records)
        robustness = {
            "test_condition": "voltage_missing_from_every_test_payload",
            "accuracy": float(accuracy_score(y_test, robustness_predictions)),
            "macro_f1": float(
                f1_score(y_test, robustness_predictions, average="macro", zero_division=0)
            ),
        }
    else:
        robustness = {"status": "not_applicable", "reason": "CSV has no voltage column"}

    feature_names = list(AMIPayloadPreprocessor.feature_names)
    schema = {
        "training_data": "SYNTHETIC",
        "features": [{"name": name, "type": "numeric"} for name in feature_names],
        "fault_classes": class_names,
    }
    metrics: dict[str, Any] = {
        "training_data": {
            "type": "SYNTHETIC",
            "row_count": int(len(data)),
            "meter_count": int(data[METER_ID].nunique()),
            "fault_class_counts": {
                str(name): int(count)
                for name, count in data[FAULT_LABEL].value_counts().items()
            },
        },
        "split": {
            "method": "GroupShuffleSplit by meter_id",
            "train_rows": int(len(train_indices)),
            "test_rows": int(len(test_indices)),
            "train_meters": int(train_data[METER_ID].nunique()),
            "test_meters": int(test_data[METER_ID].nunique()),
            "cross_validation": f"GroupKFold, {cv_splits} folds by meter_id",
        },
        "selected_classifier": selected_name,
        "fault_classification": {"cross_validation": cv_results, "test": test_results},
        "anomaly_detection": {"test": anomaly_metrics},
        "robustness": robustness,
        "feature_importance": _feature_importance(selected_classifier),
    }

    joblib.dump(selected_classifier, output_dir / ARTIFACT_NAMES["classifier"])
    joblib.dump(detector, output_dir / ARTIFACT_NAMES["detector"])
    joblib.dump(encoder, output_dir / ARTIFACT_NAMES["label_encoder"])
    (output_dir / ARTIFACT_NAMES["feature_schema"]).write_text(
        json.dumps(schema, indent=2), encoding="utf-8"
    )
    shap_summary = (
        {"status": "skipped", "reason": "Skipped by --quick."}
        if quick
        else _shap_summary(selected_classifier, test_records, output_dir / ARTIFACT_NAMES["shap"])
    )
    metrics["shap"] = shap_summary
    metrics_path = output_dir / ARTIFACT_NAMES["metrics"]
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    saved_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    (output_dir / ARTIFACT_NAMES["model_card"]).write_text(
        _model_card(saved_metrics), encoding="utf-8"
    )
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train VIDYUTSETU models from a labeled SYNTHETIC AMI CSV."
    )
    parser.add_argument(
        "--data-csv",
        required=True,
        type=Path,
        help="CSV exported from synthetic training data, with fault_label and is_anomaly_label",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("app/ml/artifacts"),
        help="Directory for trained models, metrics, and schema (default: app/ml/artifacts)",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use fewer CV folds and search iterations; skip SHAP analysis",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    training_data = load_training_data(args.data_csv)
    metrics = train(training_data, args.output_dir, seed=args.seed, quick=args.quick)
    LOGGER.info(
        "Training complete on SYNTHETIC data; selected classifier: %s",
        metrics["selected_classifier"],
    )
    LOGGER.info("Artifacts written to %s", args.output_dir)


if __name__ == "__main__":
    main()
