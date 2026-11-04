import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import { Construct } from "constructs";
import { fileURLToPath } from "node:url";

const lambdaDir = fileURLToPath(new URL("../lambda", import.meta.url));
const builderDir = fileURLToPath(new URL("../lambda_builder", import.meta.url));
const secretParameters = ["/docket/GROQ_API_KEY", "/docket/GOOGLE_API_KEY"];

export interface RemarkPipelineProps {
  dataBucket: s3.IBucket;
  signingKeyAlias: string;
  remarkZipKey?: string;
}

export class RemarkPipeline extends Construct {
  readonly stateMachine: sfn.StateMachine;
  readonly batchStateMachine: sfn.StateMachine;
  readonly handler: lambda.Function;
  readonly reindex: lambda.Function;
  readonly builder: lambda.Function;

  constructor(scope: Construct, id: string, props: RemarkPipelineProps) {
    super(scope, id);
    const { dataBucket } = props;
    const code = lambda.Code.fromAsset(lambdaDir, { exclude: ["**/__pycache__/**"] });
    const logGroup = (name: string) =>
      new logs.LogGroup(this, name, { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: cdk.RemovalPolicy.DESTROY });
    const shared = {
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      code,
      memorySize: 256,
      timeout: cdk.Duration.seconds(60),
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        DATA_PREFIX: "data/",
        SIGNING_KEY_ALIAS: props.signingKeyAlias,
      },
    };

    const planner = new lambda.Function(this, "Planner", {
      ...shared,
      handler: "plan.handler",
      description: "Docket: read the scheme version a new schemes/*.json names",
      logGroup: logGroup("PlannerLogs"),
    });
    dataBucket.grantRead(planner);

    this.builder = new lambda.Function(this, "PackageBuilder", {
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      code: lambda.Code.fromAsset(builderDir),
      handler: "build.handler",
      memorySize: 2048,
      ephemeralStorageSize: cdk.Size.gibibytes(2),
      timeout: cdk.Duration.minutes(10),
      description: "Docket: assemble the re-mark Lambda package from PyPI wheels inside AWS",
      logGroup: logGroup("BuilderLogs"),
    });
    dataBucket.grantReadWrite(this.builder, "build/*");

    this.reindex = new lambda.Function(this, "Reindex", {
      ...shared,
      handler: "plan.reindex",
      description: "Docket: rebuild data/index.json for the verification page",
      logGroup: logGroup("ReindexLogs"),
    });
    dataBucket.grantReadWrite(this.reindex, "data/*");

    this.handler = new lambda.Function(this, "RemarkScript", {
      ...shared,
      code: props.remarkZipKey ? lambda.Code.fromBucket(dataBucket, props.remarkZipKey) : code,
      handler: "bootstrap.handler",
      memorySize: 1024,
      timeout: cdk.Duration.minutes(15),
      description: "Docket: mark or re-mark one script with the Strands graph",
      logGroup: logGroup("RemarkLogs"),
      environment: {
        ...shared.environment,
        DOCKET_STORE: `s3://${dataBucket.bucketName}/data`,
        DOCKET_INPUT_BUCKET: dataBucket.bucketName,
        DOCKET_KMS_KEY: props.signingKeyAlias,
        DOCKET_AWS_REGION: cdk.Stack.of(this).region,
        DOCKET_READER_A: "groq:qwen/qwen3.8-27b",
        DOCKET_READER_B: "gemini:gemini-3.5-flash-lite",
        DOCKET_DESIGN: "1",
        SECRET_PARAMETERS: secretParameters.join(","),
      },
    });
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameters"],
        resources: secretParameters.map((name) =>
          cdk.Stack.of(this).formatArn({ service: "ssm", resource: "parameter", resourceName: name.slice(1) }),
        ),
      }),
    );
    dataBucket.grantReadWrite(this.handler);
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"],
        resources: ["*"],
        conditions: { "ForAnyValue:StringEquals": { "kms:ResourceAliases": props.signingKeyAlias } },
      }),
    );

    const invoke = (id: string, fn: lambda.IFunction, payload: Record<string, unknown> | null, resultPath: string) => {
      const task = new tasks.LambdaInvoke(this, id, {
        lambdaFunction: fn,
        payload: payload ? sfn.TaskInput.fromObject(payload) : undefined,
        resultPath,
        payloadResponseOnly: true,
        retryOnServiceExceptions: true,
      });
      return task;
    };
    const perScript = (id: string) => {
      const one = invoke(`${id}One`, this.handler, null, "$");
      one.addRetry({ errors: ["States.TaskFailed"], interval: cdk.Duration.seconds(20), maxAttempts: 2, backoffRate: 2 });
      return one;
    };

    const readScheme = invoke("ReadScheme", planner, null, "$.scheme");
    const bump = invoke("BumpScheme", this.handler, { action: "bump", "schemeVersion.$": "$.scheme.schemeVersion" }, "$.bump");
    const remarkEach = new sfn.Map(this, "RemarkEachAffectedScript", {
      itemsPath: "$.bump.items",
      maxConcurrency: 4,
      resultPath: "$.outcomes",
    });
    remarkEach.itemProcessor(perScript("Remark"));
    const publish = invoke(
      "PublishRevocations",
      this.handler,
      { action: "publish-revocations", "outcomes.$": "$.outcomes", "from.$": "$.bump.from", "to.$": "$.bump.to" },
      "$.revocations",
    );
    const refreshAfterRemark = invoke("RefreshIndexAfterRemark", this.reindex, {}, "$.index");

    this.stateMachine = new sfn.StateMachine(this, "RemarkStateMachine", {
      definitionBody: sfn.DefinitionBody.fromChainable(readScheme.next(bump).next(remarkEach).next(publish).next(refreshAfterRemark)),
      timeout: cdk.Duration.minutes(90),
      comment: "Docket: a new scheme version re-marks every affected script, then publishes the revocation list",
    });

    const markEach = new sfn.Map(this, "MarkEachScript", {
      itemsPath: "$.items",
      maxConcurrency: 4,
      resultPath: "$.outcomes",
    });
    markEach.itemProcessor(perScript("Mark"));
    const refreshAfterBatch = invoke("RefreshIndexAfterBatch", this.reindex, {}, "$.index");
    this.batchStateMachine = new sfn.StateMachine(this, "BatchStateMachine", {
      definitionBody: sfn.DefinitionBody.fromChainable(markEach.next(refreshAfterBatch)),
      timeout: cdk.Duration.minutes(90),
      comment: "Docket: mark a class set, one Strands graph run per script",
    });

    new events.Rule(this, "SchemeVersionCreated", {
      description: "Docket: a new schemes/*.json starts the re-mark",
      eventPattern: {
        source: ["aws.s3"],
        detailType: ["Object Created"],
        detail: {
          bucket: { name: [dataBucket.bucketName] },
          object: { key: [{ wildcard: "schemes/*.json" }] },
        },
      },
      targets: [
        new targets.SfnStateMachine(this.stateMachine, {
          input: events.RuleTargetInput.fromObject({
            bucket: events.EventField.fromPath("$.detail.bucket.name"),
            key: events.EventField.fromPath("$.detail.object.key"),
          }),
        }),
      ],
    });
  }
}
