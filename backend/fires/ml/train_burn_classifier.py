"""
Trains a burn / no-burn classifier from the S1+S2 time-series CSV.

Every point in backend/data/s1_s2_composite_stubble_burn_long_format.csv is a
confirmed FIRMS fire detection (see fires/gee_fetcher.py), so the CSV has no
built-in negative class. Instead, each point's own observations *before* its
fire_date serve as the "unburned" examples and observations *after* it serve
as the "burned" examples -- the classifier learns the spectral/radar
signature change (NDVI/NBR crash, VV/VH shift) that a burn leaves behind,
using each field's pre-fire values as its own baseline.

Run from backend/: ../venv/bin/python -m fires.ml.train_burn_classifier
"""
import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(BASE_DIR, "data", "s1_s2_composite_stubble_burn_long_format.csv")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "burn_classifier.joblib")

RAW_BANDS = ["NDVI", "NDWI", "NBR", "NDRE", "VV", "VH"]


def load_consolidated(csv_path):
    """Each (point_id, image_date) is split across separate S1-only and
    S2-only rows; collapse them into one row per observation."""
    df = pd.read_csv(csv_path)
    df["fire_date"] = pd.to_datetime(df["fire_date"])
    df["image_date"] = pd.to_datetime(df["image_date"])
    agg = {b: "max" for b in RAW_BANDS}  # only one source has a value per band per row
    agg.update({"longitude": "first", "latitude": "first", "fire_date": "first"})
    return df.groupby(["point_id", "image_date"], as_index=False).agg(agg)


def add_features(df):
    df["days_since_fire"] = (df["image_date"] - df["fire_date"]).dt.days
    df["label"] = (df["days_since_fire"] >= 0).astype(int)

    pre_fire = df[df["days_since_fire"] < 0]
    baseline = pre_fire.groupby("point_id")[RAW_BANDS].median().add_prefix("baseline_")
    df = df.merge(baseline, on="point_id", how="inner")  # drop points with no pre-fire baseline

    for b in RAW_BANDS:
        df[f"delta_{b}"] = df[b] - df[f"baseline_{b}"]

    return df


def main():
    df = load_consolidated(CSV_PATH)
    df = add_features(df)

    feature_cols = RAW_BANDS + [f"delta_{b}" for b in RAW_BANDS]
    df = df.dropna(subset=feature_cols)
    print(f"Training on {len(df)} observations from {df['point_id'].nunique()} fire points.")
    print(df["label"].value_counts().rename({0: "pre-fire", 1: "post-fire"}))

    X, y, groups = df[feature_cols], df["label"], df["point_id"]

    # Split by point_id, not by row, so pre/post pairs from the same field
    # never leak across the train/test boundary.
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(X, y, groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    # Mirrors the hyperparameters used by the GEE smileRandomForest
    # classifier in fires/stage_fetcher.py for consistency across the project.
    clf = RandomForestClassifier(
        n_estimators=150,
        min_samples_leaf=10,
        max_leaf_nodes=128,
        random_state=42,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]
    print("\n--- Evaluation on held-out fire points ---")
    print(classification_report(y_test, y_pred, target_names=["pre-fire", "post-fire"]))
    print("Confusion matrix:\n", confusion_matrix(y_test, y_pred))
    print("ROC-AUC:", roc_auc_score(y_test, y_proba))

    importances = pd.Series(clf.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\nFeature importances:\n", importances)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({"model": clf, "feature_cols": feature_cols}, MODEL_PATH)
    print(f"\nSaved model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
