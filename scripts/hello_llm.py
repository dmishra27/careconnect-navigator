from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_openai import DatabricksOpenAI

from careconnect.config import ProjectConfig

ROOT = Path(__file__).resolve().parents[1]
cfg = ProjectConfig.from_yaml(ROOT / "project_config.yml", env="dev")

mlflow.set_tracking_uri("databricks")
me = WorkspaceClient().current_user.me().user_name
mlflow.set_experiment(f"/Users/{me}/{cfg.experiment_name}")
mlflow.openai.autolog()

client = DatabricksOpenAI()
resp = client.chat.completions.create(
    model=cfg.llm_endpoint,
    messages=[
        {"role": "system", "content": "You are a helpful NHS patient services assistant."},
        {
            "role": "user",
            "content": "In one sentence, what does a patient services contact centre do?",
        },
    ],
    max_tokens=100,
)
print(resp.choices[0].message.content)
