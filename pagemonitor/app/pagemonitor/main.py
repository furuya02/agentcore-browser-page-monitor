import contextlib
import os
from datetime import datetime, timezone, timedelta

import boto3
import requests
from browser_use import Agent as BrowserUseAgent
from browser_use.browser.session import BrowserSession as BU_BrowserSession
from browser_use.browser import BrowserProfile as BU_BrowserProfile
from browser_use.llm.aws.chat_bedrock import ChatAWSBedrock
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.tools.browser_client import BrowserClient
from model.load import load_model

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "PageMonitorState")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")

table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMODB_TABLE)
JST = timezone(timedelta(hours=9))


@tool
async def browse_page(url: str) -> str:
    """AgentCore Browser で Web ページの情報を抽出する"""
    client = BrowserClient(region=AWS_REGION)
    bu_session = None
    try:
        client.start()
        ws_url, headers = client.generate_ws_headers()

        profile = BU_BrowserProfile(headers=headers, timeout=180000, enable_default_extensions=False)
        bu_session = BU_BrowserSession(cdp_url=ws_url, browser_profile=profile)
        await bu_session.start()

        bedrock_chat = ChatAWSBedrock(
            model=LLM_MODEL_ID,
            aws_region=AWS_REGION,
            session=boto3.Session(region_name=AWS_REGION),
        )
        browser_agent = BrowserUseAgent(
            task=f"以下のURLを開き、ページの全テキスト情報を構造化して抽出してください。\nURL: {url}",
            llm=bedrock_chat,
            browser_session=bu_session,
        )
        result = await browser_agent.run()
        return str(result)
    finally:
        if bu_session:
            with contextlib.suppress(Exception):
                await bu_session.close()
        with contextlib.suppress(Exception):
            client.stop()


@tool
def get_previous_content(url: str) -> str:
    """DynamoDB から前回取得したページ内容を取得する"""
    item = table.get_item(Key={"url": url}).get("Item", {})
    if item.get("content"):
        return f"前回取得日時: {item.get('updated_at', '不明')}\n\n{item['content']}"
    return ""


@tool
def save_content(url: str, content: str, diff_summary: str) -> str:
    """今回取得したページ内容を DynamoDB に保存する"""
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    table.put_item(Item={"url": url, "content": content, "updated_at": now, "diff_summary": diff_summary})
    return f"保存完了: {now}"


@tool
def notify_slack(message: str) -> str:
    """Slack に変更検知の通知を送信する"""
    if not SLACK_WEBHOOK_URL:
        return "Slack Webhook URL 未設定。スキップ。"
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
    return "送信完了" if r.status_code == 200 else f"送信失敗: {r.status_code}"


SYSTEM_PROMPT = """あなたは Web ページの変更を監視するエージェントです。
1. browse_page で指定 URL のページ内容を取得
2. get_previous_content で前回の内容を取得
3. 比較: 初回→通知不要 / 変更なし→報告 / 変更あり→要約
4. save_content で保存
5. 変更時のみ notify_slack で通知（:bell: *ページ変更検知* URL/日時/変更内容）
"""

app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload, context):
    url = payload.get("url", "")
    prompt = payload.get("prompt", f"以下の URL のページを確認してください: {url}")
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=load_model(), tools=[browse_page, get_previous_content, save_content, notify_slack])
    async for event in agent.stream_async(prompt):
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]

if __name__ == "__main__":
    app.run()
