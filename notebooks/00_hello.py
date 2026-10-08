# Databricks notebook source
# MAGIC %md
# MAGIC # CareConnect: hello notebook
# MAGIC A notebook stored as a .py file, so Git diffs and code review stay clean.

# COMMAND ----------

spark.sql("SELECT current_user() AS me, current_catalog() AS catalog").show()

# COMMAND ----------

spark.read.table("samples.nyctaxi.trips").limit(5).show()
