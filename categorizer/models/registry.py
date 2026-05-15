from __future__ import annotations

import os
import tempfile

import joblib
from google.cloud import storage

MODEL_BLOB = "models/spend-classifier/champion.joblib"


def _bucket() -> storage.Bucket:
    client = storage.Client()
    return client.bucket(os.environ["GCS_MODEL_BUCKET"])


def register_model(bundle: dict) -> None:
    """Serialize the model bundle to GCS, replacing any previous champion."""
    bucket = _bucket()
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
        joblib.dump(bundle, f.name)
        tmp_path = f.name
    bucket.blob(MODEL_BLOB).upload_from_filename(tmp_path)
    os.unlink(tmp_path)
    print(f"Model saved to gs://{bucket.name}/{MODEL_BLOB}")


def load_model() -> dict:
    """Load the champion model bundle from GCS."""
    bucket = _bucket()
    blob = bucket.blob(MODEL_BLOB)
    if not blob.exists():
        raise FileNotFoundError(
            f"No model found at gs://{bucket.name}/{MODEL_BLOB}. "
            "Run 'python main.py' first to train and register the model."
        )
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
        blob.download_to_filename(f.name)
        bundle = joblib.load(f.name)
    os.unlink(f.name)
    return bundle
