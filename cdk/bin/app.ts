#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { PageMonitorStack } from "../lib/page-monitor-stack";

const app = new cdk.App();

new PageMonitorStack(app, "PageMonitorStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "ap-northeast-1",
  },
});
