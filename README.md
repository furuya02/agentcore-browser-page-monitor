# AgentCore Browser Page Monitor

A web page change detection system using Amazon Bedrock AgentCore Browser. Automatically monitors web pages, detects changes by comparing with previous content, and sends notifications to Slack.

[Japanese README](README.ja.md)

## Architecture

```
EventBridge (daily) --> Lambda (trigger) --> AgentCore Runtime (agent)
                                                |
                                                +-- AgentCore Browser (page extraction)
                                                +-- Bedrock Claude (LLM)
                                                +-- DynamoDB (content storage)
                                                +-- Slack (notification)
```

## Components

| Component | Description |
|-----------|-------------|
| `pagemonitor/app/pagemonitor/main.py` | Agent with 4 tools: browse_page, get_previous_content, save_content, notify_slack |
| `cdk/` | Supporting infrastructure (Lambda, EventBridge, DynamoDB) |
| `target-page/` | Sample pricing page for monitoring (S3 static hosting) |

## Prerequisites

- AWS CLI configured for ap-northeast-1
- [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/) (`agentcore`)
- Node.js / pnpm
- Slack workspace with admin access

## Setup

### 1. Set up Slack Webhook

1. Go to [Slack API](https://api.slack.com/apps) and create a new App
2. Enable Incoming Webhooks
3. Select a notification channel (e.g., `#page-monitor`) and get the Webhook URL
4. Test:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test notification"}' \
     https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXX
   ```

### 2. Deploy the target page to S3

```bash
cd target-page
./deploy.sh <bucket-name>
```

Note the HTTPS URL (HTTP URLs are blocked by AgentCore Browser):
```
https://<bucket-name>.s3.ap-northeast-1.amazonaws.com/index.html
```

### 3. Create AgentCore project and apply agent code

```bash
cd pagemonitor

# Create project (generates agentcore/ directory)
agentcore create --name pagemonitor --defaults --build CodeZip --output-dir .
cd pagemonitor

# Replace generated code with pre-configured agent
cp -f ../app/pagemonitor/main.py app/pagemonitor/main.py
cp -f ../app/pagemonitor/model/load.py app/pagemonitor/model/load.py
cp -f ../app/pagemonitor/model/__init__.py app/pagemonitor/model/__init__.py
cp -f ../app/pagemonitor/pyproject.toml app/pagemonitor/pyproject.toml

# Remove unnecessary generated files
rm -rf app/pagemonitor/mcp_client
```

### 4. Configure environment variables

Edit `agentcore/agentcore.json` and add `envVars` to the runtime definition. Also change `"name"` from `"pagemonitor"` to `"agent"`:

```json
{
  "runtimes": [
    {
      "name": "agent",
      ...
      "envVars": [
        {"name": "DYNAMODB_TABLE", "value": "PageMonitorState"},
        {"name": "AWS_REGION", "value": "ap-northeast-1"},
        {"name": "LLM_MODEL_ID", "value": "apac.anthropic.claude-sonnet-4-20250514-v1:0"},
        {"name": "SLACK_WEBHOOK_URL", "value": "<your-slack-webhook-url>"},
        {"name": "MONITOR_URL", "value": "https://<bucket-name>.s3.ap-northeast-1.amazonaws.com/index.html"}
      ]
    }
  ]
}
```

### 5. Deploy AgentCore agent

```bash
agentcore deploy
agentcore status  # Note the Runtime ARN
```

### 6. Add IAM permissions

```bash
# Get the role name
aws iam list-roles --query "Roles[?contains(RoleName, 'pagemonitor')].RoleName" --output text

# Add AgentCore Browser permissions
aws iam put-role-policy \
  --role-name "<role-name>" \
  --policy-name "AgentCoreBrowserAccess" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "bedrock-agentcore:*", "Resource": "*"}]
  }'

# Add DynamoDB permissions
aws iam put-role-policy \
  --role-name "<role-name>" \
  --policy-name "DynamoDBPageMonitorAccess" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem"], "Resource": "arn:aws:dynamodb:ap-northeast-1:<account-id>:table/PageMonitorState"}]
  }'
```

### 7. Deploy supporting infrastructure (CDK)

```bash
cd ../../cdk
pnpm install
pnpm cdk bootstrap  # first time only
pnpm cdk deploy --parameters AgentCoreRuntimeArn=<runtime-arn>
```

## Verification

### Initial run

1. AWS Console -> Lambda -> `page-monitor-trigger` -> Test with `{}`
2. Verify: DynamoDB has a new record, no Slack notification

### Change detection test

1. Edit `target-page/index.html` (e.g., change a price)
2. Redeploy: `cd target-page && ./deploy.sh <bucket-name>`
3. Run Lambda again
4. Verify: Slack notification arrives with change details

### CLI verification

```bash
agentcore invoke '{}'
```

## Key Technical Notes

- **HTTPS required**: AgentCore Browser blocks HTTP URLs. Use `https://<bucket>.s3.<region>.amazonaws.com/index.html`.
- **LLM class**: Use `browser_use.llm.aws.chat_bedrock.ChatAWSBedrock`, not `langchain_aws.ChatBedrockConverse`.
- **browser-use version**: Pinned to `0.12.6` for compatibility.

## Cleanup

```bash
# Remove supporting infrastructure
cd cdk && pnpm cdk destroy

# Remove AgentCore Runtime
cd pagemonitor/pagemonitor/agentcore/cdk && npm install && npx cdk destroy

# Remove S3 bucket
aws s3 rb s3://<bucket-name> --force
```

## Related

- [Amazon Bedrock AgentCore Browser sample (DevelopersIO)](https://dev.classmethod.jp/articles/amazon-bedrock-agentcore-agentcore-browser-sample/)
