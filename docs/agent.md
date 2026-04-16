# エージェントコード（main.py）の解説

## 全体構成

`main.py` は以下の3つの層で構成されています。

```
エントリポイント (invoke)
  └── Strands Agent（オーケストレーション）
        └── 4つのツール
              ├── browse_page       ← AgentCore Browser + browser-use
              ├── get_previous_content  ← DynamoDB 読み取り
              ├── save_content      ← DynamoDB 書き込み
              └── notify_slack      ← Slack Webhook
```

Strands Agent がシステムプロンプトに従って、4つのツールをどの順序で呼ぶかを自律的に判断します。

---

## 環境変数

```python
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "PageMonitorState")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
MONITOR_URL = os.environ.get("MONITOR_URL", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")
```

すべて `agentcore.json` の `envVars` で AgentCore Runtime に渡されます。コードにハードコードされた値はデフォルト値として使用されます。

---

## ツール詳細

### 1. browse_page — ページ内容の取得

```python
@tool
async def browse_page(url: str) -> str:
```

AgentCore Browser を使って Web ページを開き、テキスト情報を構造化して抽出します。

**処理フロー:**

```
BrowserClient.start()          ← AgentCore Browser のセッションを開始
    ↓
generate_ws_headers()          ← WebSocket 接続用の SigV4 署名付きヘッダーを生成
    ↓
BrowserSession(cdp_url=...)    ← CDP (Chrome DevTools Protocol) で接続
    ↓
BrowserSession.start()         ← ブラウザセッションを開始
    ↓
ChatAWSBedrock(...)            ← browser-use 用の LLM を初期化
    ↓
BrowserUseAgent.run()          ← ページにナビゲートし、テキストを抽出
    ↓
BrowserSession.close()         ← セッションを閉じる
BrowserClient.stop()           ← ブラウザを停止
```

**重要なポイント:**

- **`BrowserClient`**: `bedrock_agentcore` SDK が提供する AgentCore Browser のクライアント。AWS 側のマネージドブラウザ環境に接続します。ローカルにブラウザは不要です。

- **`BrowserProfile(headers=headers, ...)`**: `generate_ws_headers()` で取得した認証ヘッダーを `BrowserProfile` に渡します。これにより CDP WebSocket 接続時に SigV4 認証が行われます。

- **`enable_default_extensions=False`**: browser-use はデフォルトで uBlock Origin 等の拡張機能を有効にしますが、AgentCore Browser のリモート環境では不要です。

- **`ChatAWSBedrock`**: browser-use が組み込みで提供する Bedrock 用 LLM クラスです。`langchain_aws.ChatBedrockConverse` ではなくこちらを使う必要があります（pydantic の `extra='forbid'` 制約により `ChatBedrockConverse` は browser-use と非互換）。

- **`session=boto3.Session(...)`**: AgentCore Runtime の IAM ロール認証を使用するために boto3 Session を渡します。これがないと `ChatAWSBedrock` が AWS 認証情報を見つけられません。

- **`BrowserUseAgent`**: browser-use のエージェント。`task` に自然言語で指示を渡すと、LLM が DOM を解析してページ内容を抽出します。CSS セレクタや XPath の指定は不要です。

### 2. get_previous_content — 前回内容の取得

```python
@tool
def get_previous_content(url: str) -> str:
```

DynamoDB から前回取得したページ内容を読み取ります。

- URL をパーティションキーとして `GetItem` を実行
- 前回データがある場合: 取得日時と内容を返す
- 初回実行（データなし）の場合: 空文字列を返す

Strands Agent はこの戻り値を見て、初回なのか変更があるのかを判断します。

### 3. save_content — 内容の保存

```python
@tool
def save_content(url: str, content: str, diff_summary: str) -> str:
```

今回取得したページ内容を DynamoDB に保存します。

- `url`: パーティションキー
- `content`: ページの全テキスト内容
- `updated_at`: 保存日時（JST）
- `diff_summary`: 差分の要約（「初回取得」「変更なし」「Basicプラン値上げ」等）

毎回 `PutItem` で上書きするため、DynamoDB には常に最新のデータのみ保持されます。

### 4. notify_slack — Slack 通知

```python
@tool
def notify_slack(message: str) -> str:
```

Slack Incoming Webhook にメッセージを POST します。

- `SLACK_WEBHOOK_URL` が未設定の場合はスキップ
- メッセージの内容は Strands Agent が生成（変更内容の要約を含む）

---

## システムプロンプト

```python
SYSTEM_PROMPT = """あなたは Web ページの変更を監視するエージェントです。
1. browse_page で指定 URL のページ内容を取得
2. get_previous_content で前回の内容を取得
3. 比較: 初回→通知不要 / 変更なし→報告 / 変更あり→要約
4. save_content で保存
5. 変更時のみ notify_slack で通知（:bell: *ページ変更検知* URL/日時/変更内容）
"""
```

Strands Agent に対して、ツールの呼び出し順序と判断基準を指示しています。Agent はこの指示に従いつつ、状況に応じて自律的に行動します。例えば：

- 初回実行時: `browse_page` → `get_previous_content`（空）→ `save_content`（通知なし）
- 変更あり: `browse_page` → `get_previous_content` → 比較 → `save_content` → `notify_slack`
- 変更なし: `browse_page` → `get_previous_content` → 比較 → `save_content`（通知なし）

---

## エントリポイント

```python
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload, context):
    url = payload.get("url", MONITOR_URL)
    prompt = f"以下の URL のページを確認してください: {url}"
    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        model=load_model(),
        tools=[browse_page, get_previous_content, save_content, notify_slack],
    )
    async for event in agent.stream_async(prompt):
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]
```

- **`BedrockAgentCoreApp`**: AgentCore Runtime のアプリケーションフレームワーク。HTTP リクエストを受け取り、`@app.entrypoint` で定義された関数に渡します。

- **`payload.get("url", MONITOR_URL)`**: Lambda から URL が渡された場合はそれを使用し、なければ環境変数 `MONITOR_URL` を使用します。通常は環境変数で設定済みのため、Lambda は空の payload `{}` を送信するだけです。

- **`Agent`**: Strands Agents のエージェント。`model` に Bedrock のモデル、`tools` に4つのツールを渡して初期化します。

- **`agent.stream_async`**: ストリーミングレスポンスでエージェントの出力を返します。AgentCore Runtime はこのストリームを呼び出し元（Lambda）に中継します。

- **`load_model()`**: `model/load.py` で定義。Bedrock の推論プロファイル ID（`apac.anthropic.claude-sonnet-4-20250514-v1:0`）を指定して `BedrockModel` を返します。このモデルは Strands Agent のオーケストレーション（ツール選択・応答生成）に使用されます。

---

## 2つの LLM の使い分け

このエージェントでは2つの LLM を異なる目的で使用しています。

| 用途 | クラス | 設定場所 |
|------|-------|---------|
| Strands Agent のオーケストレーション | `strands.models.bedrock.BedrockModel` | `model/load.py` |
| browser-use のブラウザ操作 | `browser_use.llm.aws.chat_bedrock.ChatAWSBedrock` | `main.py` の `browse_page` 内 |

- **BedrockModel**: ツールの選択、差分の比較判断、応答の生成を行います
- **ChatAWSBedrock**: ブラウザのページを解析し、DOM からテキスト情報を抽出します

---

## ChatAWSBedrock の詳細

### なぜ ChatAWSBedrock を使うのか

browser-use の LLM として `langchain_aws.ChatBedrockConverse` ではなく `browser_use.llm.aws.chat_bedrock.ChatAWSBedrock` を使う必要があります。理由は以下の通りです。

**`ChatBedrockConverse` で発生する問題:**

1. **pydantic `extra='forbid'` エラー**: browser-use が内部で `setattr(llm, '_verified_api_keys', True)` を実行するが、`ChatBedrockConverse` は pydantic モデルの `extra='forbid'` 設定により、宣言済みフィールド以外の属性設定を拒否する
2. **`model_name` 属性不足**: browser-use が `agent.llm.model_name` でモデル名を取得しようとするが、`ChatBedrockConverse` にはこの属性がない
3. **`output_format` kwargs 非対応**: browser-use が `ainvoke(messages, output_format=AgentOutput)` を呼び出すが、`ChatBedrockConverse` はこの kwargs を処理できない

**`ChatAWSBedrock` ではこれらが全て解決する:**

| 問題 | ChatBedrockConverse | ChatAWSBedrock |
|------|---------------------|----------------|
| `setattr` | NG（pydantic `extra='forbid'`） | OK（dataclass） |
| `model_name` | なし | あり |
| `output_format` kwargs | 非対応 | **対応** |
| `provider` 属性 | なし | `aws_bedrock` |

### クラス構成

`ChatAWSBedrock` は Python の `dataclass` で実装されています（pydantic ではない）。

```python
@dataclass
class ChatAWSBedrock(BaseChatModel):
    # モデル設定
    model: str = 'anthropic.claude-3-5-sonnet-20240620-v1:0'
    max_tokens: int | None = 4096
    temperature: float | None = None

    # AWS 認証
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_region: str | None = None
    aws_sso_auth: bool = False
    session: 'Session | None' = None  # boto3 Session
```

### 認証方法

3つの認証方法をサポート:

1. **`session` を渡す**（今回の方式）: `session.client('bedrock-runtime')` で IAM ロール認証を使用
2. **環境変数**: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
3. **SSO**: `aws_sso_auth=True`

AgentCore Runtime では IAM ロールが自動的に付与されるため、`session=boto3.Session()` を渡すだけで認証が完了します。

```python
bedrock_chat = ChatAWSBedrock(
    model=LLM_MODEL_ID,
    aws_region=AWS_REGION,
    session=boto3.Session(region_name=AWS_REGION),  # IAM ロール認証
)
```

### ainvoke メソッド

browser-use がブラウザ操作の各ステップで呼び出すメソッドです。2つのモードがあります。

**テキスト応答モード** (`output_format=None`):

```python
response = await llm.ainvoke(messages)
# → ChatInvokeCompletion(completion="テキスト応答")
```

通常のテキスト応答を返します。

**構造化出力モード** (`output_format=SomePydanticModel`):

```python
response = await llm.ainvoke(messages, output_format=AgentOutput)
# → ChatInvokeCompletion(completion=AgentOutput(...))
```

Bedrock の tool calling を使って構造化出力を返します。browser-use は各ステップで `AgentOutput`（次のアクションを定義する pydantic モデル）を取得するためにこのモードを使用します。

内部的には以下の処理が行われます:

1. pydantic モデルの JSON Schema を Bedrock のツール定義に変換
2. `client.converse(modelId=..., toolConfig={"tools": [...]})` で Bedrock API を呼び出し
3. レスポンスの `toolUse` から入力値を取得し、pydantic モデルに変換

```python
# pydantic → Bedrock ツール定義
tools = [{"toolSpec": {"name": "extract_agentoutput", "inputSchema": {"json": schema}}}]

# Bedrock API 呼び出し
response = client.converse(modelId=self.model, messages=..., toolConfig={"tools": tools})

# レスポンスからパース
output_format.model_validate(tool_input)
```

この `output_format` の仕組みが `langchain_aws.ChatBedrockConverse` にはなく、browser-use との互換性問題の根本原因でした。
