#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { DocketStack } from "../lib/docket-stack.js";

const app = new cdk.App();
cdk.Tags.of(app).add("project", "docket");

new DocketStack(app, "DocketStack", {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: "ap-south-1" },
  description: "Docket: verification site, credential data and the re-mark trigger",
});
