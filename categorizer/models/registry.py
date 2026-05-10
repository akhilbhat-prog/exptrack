from __future__ import annotations

import os
import tempfile
from pathlib import Path

import joblib
import mlflow
import mlflow.pyfunc

MODEL_NAME = "spend-classifier"
CHAMPION_ALIAS = "champion"

mlflow.set_tracking_uri((Path(__file__).parent.parent / "mlruns").as_uri())


class _BundleModel(mlflow.pyfunc.PythonModel):
    """Thin pyfunc wrapper so the bundle travels through the MLflow registry."""

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        self.bundle = joblib.load(context.artifacts["bundle"])

    def predict(self, context, model_input, params=None):
        raise NotImplementedError("Access the bundle via unwrap_python_model().bundle")


def register_model(bundle: dict) -> str:
    """
    Log the model bundle to MLflow, register it in the Model Registry under
    MODEL_NAME, and promote it as the new champion. Returns the model URI.
    """
    mlflow.set_experiment(MODEL_NAME)

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = os.path.join(tmpdir, "bundle.joblib")
        joblib.dump(bundle, bundle_path)

        with mlflow.start_run():
            model_info = mlflow.pyfunc.log_model(
                artifact_path="model",
                python_model=_BundleModel(),
                artifacts={"bundle": bundle_path},
            )
            run_id = mlflow.active_run().info.run_id

    model_version = mlflow.register_model(
        model_uri=f"runs:/{run_id}/model",
        name=MODEL_NAME,
    )

    client = mlflow.MlflowClient()
    client.set_registered_model_alias(MODEL_NAME, CHAMPION_ALIAS, model_version.version)

    print(f"Model registered: {MODEL_NAME} v{model_version.version} (@{CHAMPION_ALIAS})")
    return f"models:/{MODEL_NAME}@{CHAMPION_ALIAS}"


def load_model() -> dict:
    """
    Load the champion model bundle from the MLflow registry.
    Raises FileNotFoundError if no model has been registered yet.
    """
    uri = f"models:/{MODEL_NAME}@{CHAMPION_ALIAS}"
    try:
        loaded = mlflow.pyfunc.load_model(uri)
    except Exception as exc:
        raise FileNotFoundError(
            f"No registered model found ({MODEL_NAME}@{CHAMPION_ALIAS}). "
            "Run 'python main.py' first to train and register the model."
        ) from exc
    return loaded.unwrap_python_model().bundle
