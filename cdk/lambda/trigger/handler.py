"""AgentCore Runtime のエージェントを呼び出す Lambda"""

import json
import os

import boto3
from botocore.config import Config

RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]


def handler(event, context):
    config = Config(read_timeout=600, connect_timeout=60)
    client = boto3.client("bedrock-agentcore", region_name="ap-northeast-1", config=config)
    client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        payload=json.dumps({}).encode(),
        contentType="application/json",
        accept="application/json",
    )
