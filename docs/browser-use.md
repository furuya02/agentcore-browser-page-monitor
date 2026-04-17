# AgentCore Browser × browser-use 詳解

本ブログで採用している **AWS Bedrock AgentCore Browser** と **[browser-use](https://github.com/browser-use/browser-use)** の組み合わせについて、「なぜこの構成なのか」「登場するライブラリの役割は何か」を整理したドキュメントです。

---

## 1. はじめに

本プロジェクトの `browse_page` ツールは、指定した URL の Web ページを開き、テキスト情報を構造化して抽出します。これを実現するために以下の2つを組み合わせています。

- **AgentCore Browser**: AWS マネージドのヘッドレスブラウザ環境
- **browser-use**: LLM にブラウザを自律操作させる OSS ライブラリ

まず AgentCore Browser が提供する機能を確認し、そこから「なぜ browser-use を使うのか」を辿っていきます。

---

## 2. AgentCore Browser とは

Amazon Bedrock AgentCore の一機能として提供される、**マネージドブラウザ環境**です。

### 提供されるもの

| 項目 | 内容 |
|---|---|
| ブラウザ実行環境 | AWS 側で起動する Chromium インスタンス（ローカル不要） |
| 接続プロトコル | CDP (Chrome DevTools Protocol) の WebSocket エンドポイント |
| 認証 | SigV4 署名付き WebSocket ヘッダー |
| ライフサイクル | `BrowserClient.start()` / `stop()` で起動・停止 |

### 提供されないもの

AgentCore Browser は **CDP で操作可能なブラウザを貸し出すだけ** です。

- ❌ ページ遷移ロジック
- ❌ DOM 解析
- ❌ LLM との統合
- ❌ アクション決定

これらは**クライアント側のライブラリで実装する必要があります**。

### 最小構成コード

```python
from bedrock_agentcore.tools.browser_client import BrowserClient

client = BrowserClient(region="ap-northeast-1")
client.start()
ws_url, headers = client.generate_ws_headers()
# 以降、ws_url に CDP で接続するのはクライアント側の責務
```

---

## 3. CDP (Chrome DevTools Protocol) とは

AgentCore Browser との通信で使われる **CDP** について、ここで整理しておきます。

### 概要

**Chrome DevTools Protocol** の略で、Google Chrome（および Chromium ベースのブラウザ）を**外部から操作・計測するためのプロトコル**です。Chrome DevTools（開発者ツール）がブラウザと通信するために使っている仕組みが、外部プログラムからも使えるように公開されています。

### 通信方式

- **WebSocket** 上で **JSON-RPC** 形式のメッセージをやり取り
- ブラウザ起動時に `--remote-debugging-port=9222` 等でポートを開くと、そのエンドポイントに接続できる

```
クライアント ⇄ WebSocket ⇄ Chromium
     (JSON-RPC で "Page.navigate" 等のコマンドを送信)
```

### 主な機能ドメイン

| ドメイン | 例 |
|---|---|
| `Page` | ページ遷移、リロード、スクリーンショット |
| `DOM` | DOM ツリーの取得・操作 |
| `Network` | リクエスト/レスポンスの傍受・改変 |
| `Runtime` | JavaScript の実行 |
| `Input` | マウス・キーボード操作のシミュレート |
| `Accessibility` | ARIA ツリーの取得 |

### CDP を使っているツール

- **Chrome DevTools**（本家）
- **Puppeteer**（Google 製、CDP ネイティブ）
- **Playwright**（CDP をサポート）
- **browser-use**（最新版は CDP 直接制御）
- **AgentCore Browser**（CDP エンドポイントを公開）

### 本プロジェクトでの位置づけ

```
BrowserUseAgent ──JSON-RPC──▶ WebSocket ──▶ AgentCore Browser の Chromium
                (CDP コマンド)   (ws_url)
```

AgentCore Browser の `generate_ws_headers()` が返す `ws_url` は、この CDP WebSocket のエンドポイントです。browser-use はそこに接続して、「ページを開け」「DOM を取れ」「クリックしろ」といった CDP コマンドを送ってブラウザを操作しています。

### 類似プロトコルとの違い

| プロトコル | 特徴 |
|---|---|
| **CDP** | Chromium 専用。低レベル・高機能・高速 |
| **WebDriver (BiDi)** | W3C 標準。全ブラウザ対応だが機能は CDP より限定的 |
| **Selenium (旧 WebDriver)** | HTTP ベース。歴史あるが低速 |

CDP は標準化されていないものの、Chromium のほぼ全機能にアクセスできるため、近年のブラウザ自動化ツールの主流になっています。

---

## 4. AgentCore Browser のクライアント選択

AgentCore Browser が提供するのは CDP エンドポイントだけなので、**クライアントは自由に選べます**。

### CDP 対応ライブラリの比較

| ライブラリ | 特徴 | 向く用途 |
|---|---|---|
| **Playwright** | Microsoft 製。CDP 接続対応。安定・高速 | ページ構造が固定のスクレイピング |
| **Puppeteer** | Google 製。CDP ネイティブ（Node.js 中心） | Node.js でのブラウザ自動化 |
| **Selenium** | CDP モードあり。歴史あり | レガシー環境互換 |
| **browser-use** | LLM がブラウザを自律操作 | **LLM に任せたい場合（今回）** |
| **生 CDP (`pycdp` 等)** | プロトコルを直接叩く | 細かい制御が必要なとき |

### なぜ browser-use を選ぶのか

本プロジェクトの用途は「**ページ構造が変わっても柔軟に本文を抽出したい**」ことです。

- **Playwright 等**: セレクタや XPath を事前に書く必要があり、ページ改修のたびにメンテナンスが必要
- **browser-use**: 自然言語で「本文を抽出して」と指示するだけで、LLM が DOM を解釈して自律対応

監視対象ページの HTML がリニューアルされてもコード修正不要、という柔軟性を優先して browser-use を選択しています。

> 💡 **固定ページの定期取得なら Playwright の方が高速・安価**（LLM 推論コストが不要）。用途に応じて選び分けるのがポイントです。

---

## 5. browser-use とは

**自然言語のタスク指示だけで、LLM がブラウザを操作して結果を返してくれる Python ライブラリ**です。

| 観点 | 従来（Playwright / Selenium 直接） | browser-use |
|---|---|---|
| 指示方法 | コードで「このセレクタを click / type」 | 自然言語で「◯◯を調べて」 |
| DOM への対応 | セレクタが壊れれば手直し | LLM が DOM を解釈して自律対応 |
| プロトコル | WebDriver / CDP | CDP |
| ランタイム | Python 同期/非同期 | Python 3.11+ / **asyncio 必須** |

最大の特徴は、**「HTML＋スクリーンショット＋アクセシビリティツリーを LLM に渡して、LLM が次のアクションを決める」** という実行ループを、ライブラリ側が隠蔽してくれる点です。

### LLM プロバイダに依存しない

browser-use は**特定の LLM プロバイダに依存しません**。`browser_use.llm` 配下に各プロバイダ用の LLM クライアントが用意されています。

| クライアント | プロバイダ |
|---|---|
| `ChatOpenAI` | OpenAI |
| `ChatAnthropic` | Anthropic 直接 |
| `ChatAWSBedrock` | **Amazon Bedrock（今回使用）** |
| `ChatGoogle` | Gemini |
| `ChatAzureOpenAI` | Azure OpenAI |
| `ChatBrowserUse` | browser-use 独自の最適化モデル |

本プロジェクトは AgentCore Runtime（AWS 実行環境）で動作するため、同じ AWS 内の Bedrock を使う `ChatAWSBedrock` を選択していますが、他プロバイダに差し替えることも可能です。

> 💡 **「browser-use × Bedrock」は本プロジェクト固有の組み合わせ**であり、browser-use 自体は Bedrock と疎結合です。

---

## 6. 登場するライブラリ・コンポーネント整理

本プロジェクトでは複数のライブラリが絡むため、各コンポーネントの役割と所属を整理します。

### 所属別の分類

| 所属 | コンポーネント | 役割 |
|---|---|---|
| **AgentCore SDK** (`bedrock_agentcore`) | `BrowserClient` | AgentCore Browser のマネージド Chromium を起動・停止 |
| **AgentCore SDK** | `BedrockAgentCoreApp` | AgentCore Runtime のエントリポイント定義 |
| **browser-use** | `BrowserProfile` | ブラウザ設定テンプレート（headers, timeout 等） |
| **browser-use** | `BrowserSession` | CDP 接続の実体（ウォッチドッグ、イベントバス） |
| **browser-use** | `Agent` (`BrowserUseAgent`) | タスクを受けて LLM にアクションを決めさせるループ本体 |
| **browser-use** | `ChatAWSBedrock` | browser-use 用の Bedrock LLM クライアント |
| **Strands Agents** | `Agent` | ツール選択・オーケストレーション（本プロジェクトの頭脳） |
| **Strands Agents** | `@tool` デコレータ | ツール定義 |
| **AWS SDK** | `boto3.Session` | Bedrock API 呼び出しの認証情報（IAM ロール） |

### 「3つのセッション」に注意

同じ「セッション」という言葉が違う意味で3回登場します。

| 名前 | 何のセッション？ |
|---|---|
| `BrowserClient` (`client`) | **AgentCore Browser** のセッション。`client.start()` で AWS 側の Chromium を起動 |
| `BrowserSession` (`bu_session`) | **browser-use 側**のセッション。CDP 接続・イベント管理 |
| `boto3.Session` | **AWS SDK**のセッション。Bedrock API の認証 |

用途が全く違うため、コードを読むときはどの「セッション」か意識する必要があります。

### 「2つの LLM」の使い分け

本プロジェクトでは LLM を2箇所で使います。

| 用途 | クラス | 役割 |
|---|---|---|
| オーケストレーション | `strands.models.bedrock.BedrockModel` | ツール選択、差分比較、通知判断 |
| ブラウザ操作 | `browser_use.llm.aws.ChatAWSBedrock` | DOM 解析、次アクションの決定 |

Strands Agent（`BedrockModel`）が「何をすべきか」を判断し、実際のブラウザ操作は `BrowserUseAgent`（`ChatAWSBedrock`）に委譲する構成です。

---

## 7. 全体アーキテクチャ

```
┌──────────────────────────────────────────────────────┐
│  Strands Agent (BedrockModel)                         │
│  ─ browse_page / get_previous_content /               │
│    save_content / notify_slack をオーケストレーション    │
└──────────────────┬───────────────────────────────────┘
                   ↓ browse_page 呼び出し
┌──────────────────────────────────────────────────────┐
│  BrowserUseAgent (browser-use)                        │
│  ─ 自然言語タスク → LLM がアクション決定 → CDP 実行     │
└──┬─────────────┬─────────────┬───────────────────────┘
   ↓             ↓             ↓
┌──────────┐ ┌──────────┐ ┌──────────────────────────┐
│ChatAWS   │ │ Tools    │ │ BrowserSession           │
│Bedrock   │ │(click等) │ │ (CDP接続)                │
│(LLM)     │ │          │ │                          │
└────┬─────┘ └────┬─────┘ └────┬─────────────────────┘
     ↓            ↓             ↓ WebSocket (CDP)
┌──────────┐  ┌─────────┐  ┌────────────────────────┐
│ Bedrock  │  │DomService│ │ AgentCore Browser      │
│ (Claude) │  │         │  │ (AWS マネージド Chromium)│
└──────────┘  └─────────┘  └────────────────────────┘
```

---

## 8. 実装コードの読み方

```python
@tool
async def browse_page(url: str) -> str:
    client = BrowserClient(region=AWS_REGION)          # ← ①AgentCore Browser クライアント
    bu_session = None
    try:
        client.start()                                 # ← ②マネージド Chromium を起動
        ws_url, headers = client.generate_ws_headers() # ← ③CDP 接続情報を取得（SigV4 署名付き）

        profile = BU_BrowserProfile(                   # ← ④browser-use の設定
            headers=headers,
            timeout=180000,
            enable_default_extensions=False,
        )
        bu_session = BU_BrowserSession(                # ← ⑤CDP で AgentCore Browser に接続
            cdp_url=ws_url,
            browser_profile=profile,
        )
        await bu_session.start()

        bedrock_chat = ChatAWSBedrock(                 # ← ⑥ブラウザ操作用 LLM
            model=LLM_MODEL_ID,
            aws_region=AWS_REGION,
            session=boto3.Session(region_name=AWS_REGION),
        )
        browser_agent = BrowserUseAgent(               # ← ⑦Agent を組み立て
            task=f"以下のURLを開き、ページの全テキスト情報を構造化して抽出してください。\nURL: {url}",
            llm=bedrock_chat,
            browser_session=bu_session,
        )
        result = await browser_agent.run()             # ← ⑧自律実行ループ
        return str(result)
    finally:
        if bu_session:
            with contextlib.suppress(Exception):
                await bu_session.close()
        with contextlib.suppress(Exception):
            client.stop()
```

### 処理フロー

```
BrowserClient.start()          ← AgentCore Browser のセッションを開始
    ↓
generate_ws_headers()          ← WebSocket 接続用の SigV4 署名付きヘッダーを生成
    ↓
BrowserSession(cdp_url=...)    ← CDP で接続
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

### 重要なポイント

- **`BrowserProfile(headers=headers, ...)`**: `generate_ws_headers()` で取得した認証ヘッダーを渡すことで、CDP WebSocket 接続時に SigV4 認証が行われます。
- **`enable_default_extensions=False`**: browser-use はデフォルトで uBlock Origin 等の拡張機能を有効にしますが、AgentCore Browser のリモート環境では不要です。
- **`session=boto3.Session(...)`**: AgentCore Runtime の IAM ロール認証を使うために boto3 Session を渡します。これがないと `ChatAWSBedrock` が AWS 認証情報を見つけられません。
- **戻り値**: `run()` は `AgentHistoryList` を返します。`str()` で全履歴の文字列表現が取れ、これを DynamoDB に保存しています。

---

## 9. browser-use の内部動作

### 9.1 Agent の実行ループ

Agent は、タスクを受け取り LLM にアクションを決めさせ、結果を観測して次のステップへ進める**ループ本体**です。

5段階のステップを `done` になるか `max_steps` に達するまで繰り返します。

1. **Context Preparation**: 現在の DOM / スクリーンショット / ファイルシステム / 可能なアクション一覧を整える
2. **LLM Output**: LLM が次のアクション（`click`, `input_text`, `navigate`, `done` など）を構造化出力（`AgentOutput`）で返す
3. **Action Execution**: Tools が CDP 経由で実行
4. **Post-Processing**: 失敗検知、完了検知、ダウンロード検知
5. **Finalization**: 履歴保存（`AgentHistoryList`）

擬似コードで表すと：

```python
async def run(self, max_steps=100):
    for step_num in range(max_steps):
        ctx = await self._prepare_context()            # 1. DOM / screenshot
        output = await self._get_model_output_with_retry(ctx)  # 2. LLM 決定
        if output.done:
            return self.history
        await self.tools.multi_act(output.action)      # 3. CDP 実行
        await self._post_process()                     # 4. 後処理
    return self.history
```

### 9.2 BrowserSession / BrowserProfile

**2層構造**で設定を分離しています。

| レイヤ | 役割 |
|---|---|
| `BrowserProfile` | 設定テンプレート（headers, timeout, 拡張機能の有無など） |
| `BrowserSession` | ランタイムの実体（CDP接続、ウォッチドッグ、イベントバス） |

### 9.3 Tools（Action Registry）

LLM が使える「アクション」のカタログ。`click`, `input_text`, `scroll`, `navigate`, `done` 等がビルトインで定義されており、LLM は構造化出力（`ActionModel`）で「次にどのアクションを呼ぶか」を指定します。

```python
# LLM の出力イメージ（内部的）
{
  "action": [
    {"click_element_by_index": {"index": 12}},
    {"input_text": {"index": 7, "text": "hello"}}
  ],
  "done": false
}
```

### 9.4 DomService

ページ状態を LLM が「読める」形に変換するパイプライン（4段階）：

1. **CDP パラレル取得**（DOM + ARIA + snapshot を並列で取得）
2. **統合ツリー生成**（`EnhancedDOMTreeNode` に融合）
3. **フィルタリング**（非インタラクティブ要素と隠れ要素を除去）
4. **シリアライズ**（LLM 用の `SerializedDOMState` とアクション用の `DOMSelectorMap` に分離）

これにより、LLM は「インタラクティブな要素だけ」にインデックスを振られた状態で DOM を見られます。

---

## 10. `ChatAWSBedrock` vs `ChatBedrockConverse`

browser-use で Bedrock を使うときは、**`browser_use.llm.aws.ChatAWSBedrock` を使う必要があります**。LangChain の `langchain_aws.ChatBedrockConverse` は使えません。

| 観点 | `browser_use.llm.aws.ChatAWSBedrock` | `langchain_aws.ChatBedrockConverse` |
|---|---|---|
| 提供元 | **browser-use 公式** | LangChain |
| 実装 | `dataclass` | `pydantic BaseModel` |
| `setattr` の可否 | OK | **`extra='forbid'` で拒否**される |
| `output_format` kwargs | **対応** | **非対応** |
| browser-use との互換性 | ✅ | ❌ |

### なぜ `ChatBedrockConverse` はダメなのか

browser-use は LLM の応答を **構造化出力（`AgentOutput`）** として受け取る必要があり、各クライアントに `output_format` という kwargs を渡します。

- `langchain_aws` の `ChatBedrockConverse` は pydantic v2 の `model_config = {"extra": "forbid"}` を設定しており、未知の属性を一切受け付けません。
- browser-use が内部で `chat.output_format = X` のように `setattr` で属性を追加しようとすると、pydantic が例外を投げます。
- さらに `output_format` という kwargs 自体が `ChatBedrockConverse.invoke()` の引数として定義されていないので、渡しても無視されます。

### `ChatAWSBedrock` のクラス構成

`ChatAWSBedrock` は Python の `dataclass` で実装されています（pydantic ではない）。

```python
@dataclass
class ChatAWSBedrock(BaseChatModel):
    model: str = 'anthropic.claude-3-5-sonnet-20240620-v1:0'
    max_tokens: int | None = 4096
    temperature: float | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_region: str | None = None
    aws_sso_auth: bool = False
    session: 'Session | None' = None  # boto3 Session
```

### 認証方法

3つの認証方法をサポート：

1. **`session` を渡す**（今回の方式）: `session.client('bedrock-runtime')` で IAM ロール認証を使用
2. **環境変数**: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
3. **SSO**: `aws_sso_auth=True`

AgentCore Runtime では IAM ロールが自動的に付与されるため、`session=boto3.Session()` を渡すだけで認証が完了します。

### ainvoke の構造化出力モード

browser-use がブラウザ操作の各ステップで呼び出す `ainvoke` には2つのモードがあります。

**テキスト応答モード** (`output_format=None`):
```python
response = await llm.ainvoke(messages)
# → ChatInvokeCompletion(completion="テキスト応答")
```

**構造化出力モード** (`output_format=SomePydanticModel`):
```python
response = await llm.ainvoke(messages, output_format=AgentOutput)
# → ChatInvokeCompletion(completion=AgentOutput(...))
```

内部的には Bedrock の tool calling を使って構造化出力を返します。この `output_format` の仕組みが `ChatBedrockConverse` にはなく、browser-use との互換性問題の根本原因でした。

---

## 11. よくある疑問

### Q1. AgentCore Browser を使うとき、browser-use は必須？

**必須ではありません**。AgentCore Browser が提供するのは CDP エンドポイントのみで、CDP に対応していれば Playwright / Puppeteer / Selenium / 生 CDP など自由に使えます。

本プロジェクトは「LLM で柔軟にページを解析したい」用途のため browser-use を選択していますが、固定ページのスクレイピングなら Playwright の方が高速・安価です。

### Q2. browser-use は Bedrock 専用？

**違います**。browser-use は LLM プロバイダに非依存で、OpenAI / Anthropic / Google / Azure / Bedrock など幅広く対応しています。本プロジェクトが `ChatAWSBedrock` を使っているのは、AgentCore Runtime と同じ AWS 内で完結させるためです。

### Q3. browser-use は Playwright を使っているの？

以前は Playwright 依存でしたが、最新版は **CDP 直接制御**（Playwright 不要）です。Chromium さえ動けば良い構成になっています。

### Q4. 何をトリガーに `done` になるの？

LLM が「タスク完了した」と判断した時、LLM が `done` アクションを構造化出力で返します。Agent はそれを検知してループを抜けます。`max_steps`（デフォルト 100）に達すると強制終了します。

### Q5. `max_steps` を明示的に指定する必要は？

本プロジェクトでは指定していません（デフォルト）。ページ取得くらいなら数ステップで完了するので問題にならないためです。

### Q6. ログやトレースはどう見るの？

`AgentHistoryList` には各ステップの履歴（LLM 応答、実行アクション、スクリーンショット）が入っています。`.save_to_file()` で JSON 保存もできます。

### Q7. なぜ `enable_default_extensions=False` ？

Chrome 拡張は起動時間を伸ばすだけでなく、AgentCore Browser 側のサンドボックスで動かないものもあるため、無効化しておくのが無難です。

### Q8. BrowserUseAgent と Strands Agent は何が違う？

| 項目 | Strands Agent | BrowserUseAgent |
|---|---|---|
| 役割 | 全体のオーケストレーション（ツール選択・判断） | ブラウザ操作と DOM 解析 |
| 使用 LLM | `BedrockModel` | `ChatAWSBedrock` |
| 入力 | ユーザープロンプト | 自然言語タスク |

Strands Agent が「何をすべきか」を判断し、ブラウザ操作が必要なら `browse_page` ツール経由で `BrowserUseAgent` に委譲する構成です。

---

## 12. 参考リンク

- [Amazon Bedrock AgentCore Browser 公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser.html)
- [browser-use GitHub](https://github.com/browser-use/browser-use)
- [browser-use 公式ドキュメント](https://docs.browser-use.com/)
- [browser-use 公式ドキュメント - Supported Models（ChatAWSBedrock の記載あり）](https://docs.browser-use.com/supported-models)
- [DeepWiki - browser-use/browser-use](https://deepwiki.com/browser-use/browser-use)
- [Browser Configuration (DeepWiki)](https://deepwiki.com/browser-use/browser-use/3.1-browser-configuration)
- [Agent Execution Lifecycle (DeepWiki)](https://deepwiki.com/browser-use/browser-use/2.1-agent-system)
- [All Parameters - browser-use](https://docs.browser-use.com/customize/browser/all-parameters)
- [AWS Bedrock 互換性 Issue #3371](https://github.com/browser-use/browser-use/issues/3371)
