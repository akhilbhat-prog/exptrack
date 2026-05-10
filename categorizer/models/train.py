from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import scipy.sparse as sp
from lightgbm import LGBMClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedKFold


TARGET_COLUMNS = {
    "type": ["final_type", "type"],
    "category": ["final_category", "category"],
    "subcategory": ["final_subcategory", "subcategory", "expense"],
}

_AMOUNT_BIN_EDGES = [100, 500, 2000]

_LGBM_PARAMS: dict = dict(
    n_estimators=300,
    learning_rate=0.05,
    max_depth=6,
    num_leaves=31,
    class_weight="balanced",
    random_state=42,
    verbose=-1,
)


def train_category_model(df: pd.DataFrame) -> dict:
    """
    Train a hierarchical 3-stage classifier: type → category → subcategory.

    Each stage conditions on the previous stage's true label during training
    (teacher forcing) and on predicted probabilities at inference time.
    """
    text_col = _resolve_column(df, ["text_combined", "entry_clean"])
    type_col = _resolve_column(df, TARGET_COLUMNS["type"])
    cat_col = _resolve_column(df, TARGET_COLUMNS["category"])
    subcat_col = _resolve_column(df, TARGET_COLUMNS["subcategory"])

    training_df = df.copy()
    training_df[text_col] = training_df[text_col].fillna("").astype(str).str.strip()

    labeled_mask = (
        (training_df[type_col].fillna("").str.strip() != "")
        & (training_df[cat_col].fillna("").str.strip() != "")
        & (training_df[subcat_col].fillna("").str.strip() != "")
    )
    training_df = training_df.loc[labeled_mask].copy()

    if training_df.empty:
        raise ValueError("No fully labeled rows available for training.")

    for col in [type_col, cat_col, subcat_col]:
        training_df[col] = training_df[col].str.strip().str.title()

    texts = training_df[text_col].tolist()
    amounts = (
        training_df["amount"].fillna(0).tolist()
        if "amount" in training_df.columns
        else [0.0] * len(training_df)
    )
    y_type = training_df[type_col].tolist()
    y_cat = training_df[cat_col].tolist()
    y_subcat = training_df[subcat_col].tolist()

    word_vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)
    char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    word_features = word_vec.fit_transform(texts)
    char_features = char_vec.fit_transform(texts)
    amount_features = build_amount_features(amounts)
    base_features = sp.hstack([word_features, char_features, amount_features], format="csr")

    print("Cross-validation (teacher-forced conditioning):")

    type_model = LGBMClassifier(**_LGBM_PARAMS)
    _log_cv_accuracy("  type", base_features, y_type)
    type_model.fit(base_features, y_type)

    type_onehot = _to_onehot(y_type, type_model.classes_)
    cat_input = sp.hstack([base_features, sp.csr_matrix(type_onehot)], format="csr")
    cat_model = LGBMClassifier(**_LGBM_PARAMS)
    _log_cv_accuracy("  category", cat_input, y_cat)
    cat_model.fit(cat_input, y_cat)

    cat_onehot = _to_onehot(y_cat, cat_model.classes_)
    subcat_input = sp.hstack(
        [base_features, sp.csr_matrix(type_onehot), sp.csr_matrix(cat_onehot)],
        format="csr",
    )
    subcat_model = LGBMClassifier(**_LGBM_PARAMS)
    _log_cv_accuracy("  subcategory", subcat_input, y_subcat)
    subcat_model.fit(subcat_input, y_subcat)

    print(
        f"Trained on {len(training_df)} labeled rows | "
        f"{len(set(y_cat))} categories | {len(set(y_subcat))} subcategories"
    )

    return {
        "word_vec": word_vec,
        "char_vec": char_vec,
        "type_model": type_model,
        "cat_model": cat_model,
        "subcat_model": subcat_model,
    }


def build_amount_features(amounts: list[float]) -> sp.csr_matrix:
    """Build a sparse matrix of log-amount + one-hot amount bins."""
    amounts_arr = np.array(amounts, dtype=float)
    amounts_arr = np.where(np.isnan(amounts_arr), 0.0, amounts_arr)

    log_amount = np.log1p(np.abs(amounts_arr)).reshape(-1, 1)

    bin_indices = np.digitize(amounts_arr, bins=_AMOUNT_BIN_EDGES)
    n_bins = len(_AMOUNT_BIN_EDGES) + 1
    bins_onehot = np.zeros((len(amounts), n_bins), dtype=np.float32)
    for i, idx in enumerate(bin_indices):
        bins_onehot[i, idx] = 1.0

    dense = np.hstack([log_amount, bins_onehot]).astype(np.float32)
    return sp.csr_matrix(dense)


def _to_onehot(labels: list[str], classes: np.ndarray) -> np.ndarray:
    class_to_idx = {cls: i for i, cls in enumerate(classes)}
    onehot = np.zeros((len(labels), len(classes)), dtype=np.float32)
    for i, label in enumerate(labels):
        idx = class_to_idx.get(label)
        if idx is not None:
            onehot[i, idx] = 1.0
    return onehot


def _log_cv_accuracy(
    stage: str, features: sp.spmatrix, labels: list[str], n_splits: int = 5
) -> None:
    labels_arr = np.array(labels)
    _, counts = np.unique(labels_arr, return_counts=True)
    min_count = int(counts.min())

    effective_splits = min(n_splits, min_count)
    if effective_splits < 2:
        print(f"{stage} CV: skipped (min class count={min_count})")
        return

    kf = StratifiedKFold(n_splits=effective_splits, shuffle=True, random_state=42)
    scores = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for train_idx, val_idx in kf.split(features, labels_arr):
            model = LGBMClassifier(**_LGBM_PARAMS)
            model.fit(features[train_idx], labels_arr[train_idx])
            preds = model.predict(features[val_idx])
            scores.append(float(np.mean(preds == labels_arr[val_idx])))

    print(
        f"{stage} CV accuracy ({effective_splits}-fold): "
        f"{np.mean(scores):.2%} ±{np.std(scores):.2%}"
    )


def _resolve_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for column in candidates:
        if column in df.columns:
            return column
    raise ValueError(f"Missing required column. Expected one of: {candidates}")
