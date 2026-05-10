from __future__ import annotations

import warnings

import numpy as np
import scipy.sparse as sp

from models.train import build_amount_features


def predict_category(model_bundle: dict, text: str, amount: float = 0.0) -> dict:
    """
    Predict category, subcategory, and type using the hierarchical chain.

    Stage 1 predicts type, stage 2 conditions on type probabilities to predict
    category, stage 3 conditions on both to predict subcategory.
    """
    word_vec = model_bundle["word_vec"]
    char_vec = model_bundle["char_vec"]
    type_model = model_bundle["type_model"]
    cat_model = model_bundle["cat_model"]
    subcat_model = model_bundle["subcat_model"]

    normalized_text = "" if text is None else str(text)
    safe_amount = (
        0.0
        if amount is None or (isinstance(amount, float) and np.isnan(amount))
        else float(amount)
    )

    word_features = word_vec.transform([normalized_text])
    char_features = char_vec.transform([normalized_text])
    amount_features = build_amount_features([safe_amount])
    base_features = sp.hstack([word_features, char_features, amount_features], format="csr")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        # Stage 1: type
        type_probs = type_model.predict_proba(base_features)[0]
        type_pred = str(type_model.classes_[int(np.argmax(type_probs))])
        type_conf = float(np.max(type_probs))

        # Stage 2: category — soft conditioning on type probability distribution
        type_probs_mat = sp.csr_matrix(type_probs.reshape(1, -1))
        cat_input = sp.hstack([base_features, type_probs_mat], format="csr")
        cat_probs = cat_model.predict_proba(cat_input)[0]
        cat_pred = str(cat_model.classes_[int(np.argmax(cat_probs))])
        cat_conf = float(np.max(cat_probs))

        # Stage 3: subcategory — soft conditioning on type + category distributions
        cat_probs_mat = sp.csr_matrix(cat_probs.reshape(1, -1))
        subcat_input = sp.hstack([base_features, type_probs_mat, cat_probs_mat], format="csr")
        subcat_probs = subcat_model.predict_proba(subcat_input)[0]
        subcat_pred = str(subcat_model.classes_[int(np.argmax(subcat_probs))])
        subcat_conf = float(np.max(subcat_probs))

    # Weighted confidence: type is easy (weight low), subcategory is hardest (weight high)
    confidence = 0.2 * type_conf + 0.3 * cat_conf + 0.5 * subcat_conf

    return {
        "category": cat_pred,
        "subcategory": subcat_pred,
        "type": type_pred,
        "confidence": confidence,
    }
