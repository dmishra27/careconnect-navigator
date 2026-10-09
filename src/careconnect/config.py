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
    landing_volume: str = "landing"
    chunk_max_tokens: int = 400
    chunk_overlap_tokens: int = 60

    @property
    def landing_path(self) -> str:
        """Unity Catalog Volume path holding the raw source files."""
        return f"/Volumes/{self.catalog}/{self.schema_name}/{self.landing_volume}"

    def table(self, name: str) -> str:
        """Fully qualified table name in this environment's schema."""
        return f"{self.catalog}.{self.schema_name}.{name}"

    @classmethod
    def from_yaml(cls, path: str | Path, env: str = "dev") -> "ProjectConfig":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if env not in raw:
            raise ValueError(f"Unknown environment '{env}'. Expected one of: {list(raw)}")
        return cls(env=env, **raw[env])
