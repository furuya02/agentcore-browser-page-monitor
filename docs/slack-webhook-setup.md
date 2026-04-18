# Slack Incoming Webhook セットアップ手順

## 1. Slack App を作成

1. [Slack API](https://api.slack.com/apps) にアクセス
2. 「Create New App」→「From scratch」を選択
3. App Name: `Page Monitor`（任意）
4. Workspace: 通知を送りたいワークスペースを選択
5. 「Create App」をクリック

## 2. Incoming Webhook を有効化

1. 左メニューの「Incoming Webhooks」をクリック
2. 「Activate Incoming Webhooks」を **On** に切り替え
3. ページ下部の「Add New Webhook to Workspace」をクリック
4. 通知を送るチャンネルを選択（例: `#monitoring`）
5. 「許可する」をクリック

## 3. Webhook URL を取得

「Webhook URL」が表示されるのでコピー:

```
https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXX
```

## 4. 動作確認

```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Webhook テスト: 正常に動作しています"}' \
  https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXX
```

指定したチャンネルにメッセージが届けば設定完了です。

