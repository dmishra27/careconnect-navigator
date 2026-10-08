from pathlib import Path

import pytest

from careconnect.config import ProjectConfig

ROOT = Path(__file__).resolve().parents[1]


def test_dev_config_loads():
    cfg = ProjectConfig.from_yaml(ROOT / "project_config.yml", "dev")
    assert cfg.llm_endpoint.startswith("databricks-")


def test_unknown_env_fails():
    with pytest.raises(ValueError):
        ProjectConfig.from_yaml(ROOT / "project_config.yml", "staging")
