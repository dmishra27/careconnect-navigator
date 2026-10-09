import pytest


@pytest.mark.integration
def test_spark_connects(spark):
    assert spark.sql("SELECT 1 AS one").collect()[0]["one"] == 1


@pytest.mark.integration
def test_landing_volume_exists(spark):
    volumes = spark.sql("SHOW VOLUMES IN workspace.careconnect_dev").collect()
    assert "landing" in [row["volume_name"] for row in volumes]
