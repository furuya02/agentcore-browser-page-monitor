"""AgentCore Runtime のエージェントを呼び出す Lambda"""

import json
import os

import boto3

MONITOR_URL = os.environ["MONITOR_URL"]
RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]


def handler(event, context):
    url = event.get("url", MONITOR_URL)

    client = boto3.client("bedrock-agentcore", region_name="ap-northeast-1")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        payload=json.dumps({
            "prompt": f"以下の URL のページを確認してください: {url}",
            "url": url,
        }).encode(),
        contentType="application/json",
        accept="application/json",
    )

    result = response["response"].read().decode("utf-8")
    return {"statusCode": 200, "body": result}
