from databricks.connect import DatabricksSession

spark = DatabricksSession.builder.serverless(True).getOrCreate()
spark.sql("SELECT current_user() AS me, current_catalog() AS catalog").show()
spark.read.table("samples.nyctaxi.trips").limit(5).show()
