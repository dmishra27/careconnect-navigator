import mlflow
from databricks_openai import DatabricksOpenAI

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Users/dmishra27@outlook.com/careconnect-dev")
mlflow.openai.autolog()  # traces every OpenAI-compatible call

client = DatabricksOpenAI()  # uses your DEFAULT profile

resp = client.chat.completions.create(
    model="databricks-meta-llama-3-3-70b-instruct",
    messages=[
        {"role": "system", "content": "You are a helpful NHS patient services assistant."},
        {"role": "user", "content": "In one sentence, what does a patient services contact centre do?"},
    ],
    max_tokens=100,
)
print(resp.choices[0].message.content)