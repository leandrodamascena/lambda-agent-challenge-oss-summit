from __future__ import annotations

import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as integrations,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3_deployment,
)
from constructs import Construct


class OssoStack(Stack):
    """Deploy the public challenge behind API Gateway."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        model_id: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        source_dir = Path(__file__).resolve().parent.parent / "lambda_src"
        skip_bundling = bool(self.node.try_get_context("skipBundling"))

        challenge_bucket = s3.Bucket(
            self,
            "ChallengeBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        leaderboard_table = dynamodb.Table(
            self,
            "LeaderboardTable",
            partition_key=dynamodb.Attribute(
                name="player_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        challenge_assets = Path(__file__).resolve().parent.parent / "challenge_assets"
        s3_deployment.BucketDeployment(
            self,
            "ChallengeAssets",
            destination_bucket=challenge_bucket,
            sources=[s3_deployment.Source.asset(str(challenge_assets))],
            prune=True,
        )

        function_code = lambda_.Code.from_asset(
            str(source_dir),
            bundling=None
            if skip_bundling
            else BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_14.bundling_image,
                platform="linux/arm64",
                command=[
                    "bash",
                    "-c",
                    "python -m pip install -r requirements.txt -t /asset-output "
                    "&& cp -R . /asset-output",
                ],
            ),
        )

        function_logs = logs.LogGroup(
            self,
            "AgentFunctionLogs",
            log_group_name="/aws/lambda/break-my-agent",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        agent_function = lambda_.Function(
            self,
            "AgentFunction",
            function_name="break-my-agent",
            description="Open-source AI red-team challenge",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            handler="app.lambda_handler",
            code=function_code,
            memory_size=1024,
            timeout=Duration.seconds(30),
            reserved_concurrent_executions=20,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=function_logs,
            environment={
                "POWERTOOLS_SERVICE_NAME": "break-my-agent",
                "POWERTOOLS_METRICS_NAMESPACE": "BreakMyAgent",
                "LOG_LEVEL": "INFO",
                "MODEL_ID": model_id,
                "CHALLENGE_BUCKET": challenge_bucket.bucket_name,
                "LEADERBOARD_TABLE": leaderboard_table.table_name,
            },
        )
        agent_function.node.add_dependency(function_logs)
        leaderboard_table.grant_read_write_data(agent_function)

        agent_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )

        agent_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[challenge_bucket.arn_for_objects("public/*")],
            )
        )

        access_logs = logs.LogGroup(
            self,
            "ApiAccessLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        http_api = apigwv2.HttpApi(
            self,
            "ChallengeApi",
            api_name="break-my-agent",
            description="Public API for the Open Source Summit challenge",
            create_default_stage=False,
        )

        integration = integrations.HttpLambdaIntegration(
            "AgentIntegration",
            agent_function,
            payload_format_version=apigwv2.PayloadFormatVersion.VERSION_2_0,
        )

        http_api.add_routes(
            path="/",
            methods=[apigwv2.HttpMethod.GET],
            integration=integration,
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
                apigwv2.HttpMethod.OPTIONS,
            ],
            integration=integration,
        )

        stage = apigwv2.CfnStage(
            self,
            "DefaultStage",
            api_id=http_api.api_id,
            stage_name="$default",
            auto_deploy=True,
            default_route_settings=apigwv2.CfnStage.RouteSettingsProperty(
                throttling_burst_limit=10,
                throttling_rate_limit=5,
            ),
            access_log_settings=apigwv2.CfnStage.AccessLogSettingsProperty(
                destination_arn=access_logs.log_group_arn,
                format=json.dumps(
                    {
                        "requestId": "$context.requestId",
                        "ip": "$context.identity.sourceIp",
                        "requestTime": "$context.requestTime",
                        "routeKey": "$context.routeKey",
                        "status": "$context.status",
                        "responseLength": "$context.responseLength",
                        "integrationLatency": "$context.integrationLatency",
                    }
                ),
            ),
        )
        stage.node.add_dependency(access_logs)

        cdk.Tags.of(self).add("Project", "BreakMyAgent")
        cdk.Tags.of(self).add("Event", "OpenSourceSummitEurope")

        CfnOutput(
            self,
            "ChallengeUrl",
            value=http_api.api_endpoint,
            description="Open this URL or encode it in the booth QR code",
        )
        CfnOutput(
            self,
            "ModelId",
            value=model_id,
            description="Bedrock model used by Strands Agents",
        )
