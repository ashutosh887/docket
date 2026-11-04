import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as kms from "aws-cdk-lib/aws-kms";
import type { Construct } from "constructs";
import { RemarkPipeline } from "./remark-pipeline.js";

export class DocketStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const privateBucket = (name: string, eventBridgeEnabled = false) =>
      new s3.Bucket(this, name, {
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        encryption: s3.BucketEncryption.S3_MANAGED,
        enforceSSL: true,
        eventBridgeEnabled,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        autoDeleteObjects: true,
      });

    const siteBucket = privateBucket("SiteBucket");
    const dataBucket = privateBucket("DataBucket", true);

    const signingKey = kms.Alias.fromAliasName(this, "CredentialKey", "alias/docket-credentials");

    const dataCache = new cloudfront.CachePolicy(this, "DataCache", {
      defaultTtl: cdk.Duration.seconds(30),
      minTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.minutes(5),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
    });

    const distribution = new cloudfront.Distribution(this, "Distribution", {
      comment: "Docket verification site",
      defaultRootObject: "index.html",
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        compress: true,
      },
      additionalBehaviors: {
        "/data/*": {
          origin: origins.S3BucketOrigin.withOriginAccessControl(dataBucket),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: dataCache,
          responseHeadersPolicy: cloudfront.ResponseHeadersPolicy.CORS_ALLOW_ALL_ORIGINS,
          compress: true,
        },
      },
    });

    const remark = new RemarkPipeline(this, "Remark", {
      dataBucket,
      signingKeyAlias: signingKey.aliasName,
      remarkZipKey: this.node.tryGetContext("remarkZip"),
    });

    new cdk.CfnOutput(this, "SiteUrl", { value: `https://${distribution.distributionDomainName}` });
    new cdk.CfnOutput(this, "SiteBucketName", { value: siteBucket.bucketName });
    new cdk.CfnOutput(this, "DataBucketName", { value: dataBucket.bucketName });
    new cdk.CfnOutput(this, "DistributionId", { value: distribution.distributionId });
    new cdk.CfnOutput(this, "SigningKeyAlias", { value: signingKey.aliasName });
    new cdk.CfnOutput(this, "RemarkStateMachineArn", { value: remark.stateMachine.stateMachineArn });
    new cdk.CfnOutput(this, "BatchStateMachineArn", { value: remark.batchStateMachine.stateMachineArn });
    new cdk.CfnOutput(this, "RemarkFunctionName", { value: remark.handler.functionName });
    new cdk.CfnOutput(this, "RemarkFunctionArn", { value: remark.handler.functionArn });
    new cdk.CfnOutput(this, "BuilderFunctionName", { value: remark.builder.functionName });
    new cdk.CfnOutput(this, "ReindexFunctionName", { value: remark.reindex.functionName });
  }
}
