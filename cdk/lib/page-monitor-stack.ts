import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import * as path from "path";

export class PageMonitorStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // DynamoDB
    const table = new dynamodb.Table(this, "PageMonitorState", {
      tableName: "PageMonitorState",
      partitionKey: { name: "url", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // パラメータ
    const monitorUrl = new cdk.CfnParameter(this, "MonitorUrl", {
      type: "String",
      description: "監視対象の URL",
    });
    const runtimeArn = new cdk.CfnParameter(this, "AgentCoreRuntimeArn", {
      type: "String",
      description: "AgentCore Runtime ARN（agentcore status で確認）",
    });

    // Lambda
    const fn = new lambda.Function(this, "TriggerFunction", {
      functionName: "page-monitor-trigger",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/trigger")),
      timeout: cdk.Duration.minutes(10),
      memorySize: 256,
      environment: {
        MONITOR_URL: monitorUrl.valueAsString,
        AGENTCORE_RUNTIME_ARN: runtimeArn.valueAsString,
      },
    });

    fn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: ["*"],
      })
    );

    // EventBridge（1日1回）
    const rule = new events.Rule(this, "DailySchedule", {
      schedule: events.Schedule.rate(cdk.Duration.days(1)),
    });
    rule.addTarget(new targets.LambdaFunction(fn));
  }
}
