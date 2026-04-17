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
MONITOR_URL = os.environ.get("MONITOR_URL", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")

table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMODB_TABLE)
JST = timezone(timedelta(hours=9))


@tool
async def browse_page(url: str) -> str:
    """AgentCore Browser で Web ページの情報を抽出する"""
    # ① AgentCore Browser のクライアント（bedrock_agentcore SDK）
    #    AWS 側のマネージド Chromium を借りるためのハンドル。ローカルにブラウザは不要。
    client = BrowserClient(region=AWS_REGION)
    bu_session = None
    try:
        # ② マネージド Chromium を起動
        #    AWS 側でブラウザインスタンスが立ち上がり、CDP (Chrome DevTools Protocol)
        #    の WebSocket エンドポイントが利用可能になる。
        client.start()

        # ③ CDP 接続用の WebSocket URL と SigV4 署名付き認証ヘッダーを取得
        #    ws_url  : CDP の WebSocket エンドポイント（wss://...）
        #    headers : WebSocket 接続時に付与する SigV4 署名付きヘッダー
        ws_url, headers = client.generate_ws_headers()

        # ④ browser-use 用のブラウザ設定（BrowserProfile）
        #    headers                       : CDP 接続時の SigV4 認証に使用
        #    timeout=180000                : CDP 操作のタイムアウト（ミリ秒）
        #    enable_default_extensions=False:
        #        browser-use はデフォルトで uBlock Origin 等の拡張を有効化するが、
        #        AgentCore Browser のサンドボックスでは動作しないため無効化。
        profile = BU_BrowserProfile(headers=headers, timeout=180000, enable_default_extensions=False)

        # ⑤ browser-use の BrowserSession で CDP 接続を確立
        #    cdp_url にマネージド Chromium の WebSocket URL を渡すことで、
        #    ローカル Chromium ではなく AgentCore Browser に繋がる。
        bu_session = BU_BrowserSession(cdp_url=ws_url, browser_profile=profile)
        await bu_session.start()

        # ⑥ ブラウザ操作用の LLM クライアント（browser-use 公式の Bedrock 統合）
        #    ※ langchain_aws.ChatBedrockConverse は browser-use 非対応
        #       （pydantic の extra='forbid' / output_format kwargs 非対応のため）
        #    ChatAWSBedrock は @dataclass 実装で output_format に対応しており、
        #    browser-use が要求する AgentOutput の構造化出力を返せる。
        #    session に boto3.Session を渡すことで、AgentCore Runtime の
        #    IAM ロール認証をそのまま使用する。
        bedrock_chat = ChatAWSBedrock(
            model=LLM_MODEL_ID,
            aws_region=AWS_REGION,
            session=boto3.Session(region_name=AWS_REGION),
        )

        # ⑦ browser-use の Agent を組み立てる
        #    task           : 自然言語のタスク指示（CSS セレクタ不要）
        #    llm            : 上で作成した ChatAWSBedrock
        #    browser_session: CDP 接続済みの BrowserSession
        browser_agent = BrowserUseAgent(
            task=f"以下のURLを開き、ページの全テキスト情報を構造化して抽出してください。\nURL: {url}",
            llm=bedrock_chat,
            browser_session=bu_session,
        )

        # ⑧ 自律実行ループを開始
        #    Agent は内部で以下の 5 ステップを done になるまで繰り返す:
        #      1. Context Preparation : DOM / screenshot / available actions を収集
        #      2. LLM Output          : 次のアクションを AgentOutput として構造化出力
        #      3. Action Execution    : Tools が CDP 経由でアクションを実行
        #      4. Post-Processing     : 失敗・完了・ダウンロードを検知
        #      5. Finalization        : AgentHistoryList に履歴を保存
        #    戻り値は AgentHistoryList。str() で全履歴を文字列化して返す。
        result = await browser_agent.run()
        return str(result)
    finally:
        # ⑨ リソースのクリーンアップ
        #    BrowserSession を先に閉じ、その後で AgentCore Browser を停止する。
        #    client.stop() を忘れるとマネージド Chromium が残り続けるため必須。
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
    url = payload.get("url", MONITOR_URL)
    prompt = f"以下の URL のページを確認してください: {url}"
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=load_model(), tools=[browse_page, get_previous_content, save_content, notify_slack])
    async for event in agent.stream_async(prompt):
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]

if __name__ == "__main__":
    app.run()
