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
    search_endpoint: str = "careconnect-search"  # Free Edition allows one AI Search endpoint
    # AUTO: HYBRID for questions with exact terms, ANN otherwise. On 61 questions it found
    # the right passage in the top 5 for 55 (ANN 52, HYBRID 52); see docs/decisions
    search_query_type: str = "AUTO"
    # Agent tools: UC functions over Databricks' MCP server plus our own search tool. Not
    # "mcp-search": the Vector Search MCP returned the superseded leaflet (docs/decisions)
    agent_tool_backend: str = "mcp"
    # Agent traces go to Unity Catalog tables named <catalog>.<schema>.<prefix>_* (Week 4)
    agent_trace_prefix: str = "careconnect_agent"

    @property
    def agent_experiment_name(self) -> str:
        """Separate MLflow experiment for agent traces, e.g. careconnect-dev-agent."""
        return f"{self.experiment_name}-agent"

    @property
    def agent_uc_experiment_name(self) -> str:
        """Experiment whose traces are stored in Unity Catalog, e.g.
        careconnect-dev-agent-uc-traces. (Not "-uc": a Week 3 experiment of that name already
        holds traces, and Databricks only links an experiment with no traces to Unity Catalog.)"""
        return f"{self.agent_experiment_name}-uc-traces"

    @property
    def chunks_index(self) -> str:
        """AI Search index kept in sync with silver_chunks."""
        return self.table("silver_chunks_index")

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
