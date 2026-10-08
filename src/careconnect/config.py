from pathlib import Path

import yaml
from pydantic import BaseModel


class ProjectConfig(BaseModel):
    env: str
    catalog: str
    schema_name: str
    experiment_name: str
    llm_endpoint: str
    judge_endpoint: str
    embedding_endpoint: str

    @classmethod
    def from_yaml(cls, path: str | Path, env: str = "dev") -> "ProjectConfig":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if env not in raw:
            raise ValueError(f"Unknown environment '{env}'. Expected one of: {list(raw)}")
        return cls(env=env, **raw[env])
