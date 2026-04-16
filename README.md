# AgentCore Browser Page Monitor

A web page change detection system using Amazon Bedrock AgentCore Browser. Automatically monitors web pages, detects changes by comparing with previous content, and sends notifications to Slack.

[日本語版 README はこちら](README.ja.md)

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
| `pagemonitor/agentcore/` | AgentCore Runtime configuration and CDK |
| `cdk/` | Supporting infrastructure (Lambda, EventBridge, DynamoDB) |
| `target-page/` | Sample pricing page for monitoring (S3 static hosting) |

## Prerequisites

- AWS CLI configured for ap-northeast-1
- [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/) (`agentcore`)
- Node.js / pnpm
- Slack workspace with admin access

## Setup

### 1. Deploy the target page to S3

```bash
cd target-page
./deploy.sh <bucket-name>
```

Note the HTTPS URL (HTTP URLs are blocked by AgentCore Browser):
```
https://<bucket-name>.s3.ap-northeast-1.amazonaws.com/index.html
```

### 2. Configure and deploy the AgentCore agent

Edit `pagemonitor/agentcore/agentcore.json` and set the `envVars`:

```json
"envVars": [
  {"name": "DYNAMODB_TABLE", "value": "PageMonitorState"},
  {"name": "AWS_REGION", "value": "ap-northeast-1"},
  {"name": "LLM_MODEL_ID", "value": "apac.anthropic.claude-sonnet-4-20250514-v1:0"},
  {"name": "SLACK_WEBHOOK_URL", "value": "<your-slack-webhook-url>"},
  {"name": "MONITOR_URL", "value": "https://<bucket-name>.s3.ap-northeast-1.amazonaws.com/index.html"}
]
```

Deploy:

```bash
cd pagemonitor
agentcore deploy
agentcore status  # Note the Runtime ARN
```

### 3. Add IAM permissions

The execution role created by `agentcore deploy` needs additional permissions:

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

### 4. Deploy supporting infrastructure (CDK)

```bash
cd cdk
pnpm install
pnpm cdk bootstrap  # first time only
pnpm cdk deploy --parameters AgentCoreRuntimeArn=<runtime-arn>
```

## Verification

### Initial run (no changes expected)

1. Go to AWS Console -> Lambda -> `page-monitor-trigger`
2. Click "Test" tab, use `{}` as test event
3. Verify:
   - Lambda completes successfully
   - DynamoDB `PageMonitorState` has a new record
   - No Slack notification (first run)

### Change detection test

1. Edit `target-page/index.html` (e.g., change a price)
2. Redeploy: `cd target-page && ./deploy.sh <bucket-name>`
3. Run Lambda again from the console
4. Verify:
   - Slack notification arrives with change details

### CLI verification

```bash
cd pagemonitor
agentcore invoke '{}'
```

## Key Technical Notes

- **HTTPS required**: AgentCore Browser blocks HTTP URLs (`net::ERR_BLOCKED_BY_CLIENT`). Use `https://<bucket>.s3.<region>.amazonaws.com/index.html` instead of S3 website hosting URLs.
- **LLM class**: Use `browser_use.llm.aws.chat_bedrock.ChatAWSBedrock`, not `langchain_aws.ChatBedrockConverse` (pydantic `extra='forbid'` incompatibility with browser-use).
- **browser-use version**: Pinned to `0.12.6` for compatibility.

## Cleanup

```bash
cd cdk && pnpm cdk destroy
cd pagemonitor && agentcore destroy
aws s3 rb s3://<bucket-name> --force
```

## Related

- [Amazon Bedrock AgentCore Browser sample (DevelopersIO)](https://dev.classmethod.jp/articles/amazon-bedrock-agentcore-agentcore-browser-sample/)
