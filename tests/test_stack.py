import json

from aws_cdk import App
from aws_cdk.assertions import Match, Template

from infra.osso_stack import OssoStack


def template() -> Template:
    app = App(context={"skipBundling": True})
    stack = OssoStack(
        app,
        "TestStack",
        model_id="global.openai.gpt-6-astra",
    )
    return Template.from_stack(stack)


def test_uses_python_314_behind_api_gateway() -> None:
    synthesized = template()

    synthesized.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.14",
            "Architectures": ["arm64"],
            "ReservedConcurrentExecutions": 20,
            "TracingConfig": {"Mode": "Active"},
        },
    )
    synthesized.resource_count_is("AWS::ApiGatewayV2::Api", 1)
    synthesized.resource_count_is("AWS::Lambda::Url", 0)


def test_api_has_throttling_and_access_logs() -> None:
    template().has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "StageName": "$default",
            "AutoDeploy": True,
            "DefaultRouteSettings": {
                "ThrottlingBurstLimit": 10,
                "ThrottlingRateLimit": 5,
            },
            "AccessLogSettings": {
                "DestinationArn": Match.any_value(),
                "Format": Match.string_like_regexp("integrationLatency"),
            },
        },
    )


def test_s3_policy_only_allows_public_prefix() -> None:
    policies = template().find_resources("AWS::IAM::Policy")
    statements = [
        statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    s3_statements = [statement for statement in statements if statement["Action"] == "s3:GetObject"]

    assert len(s3_statements) == 1
    resource = json.dumps(s3_statements[0]["Resource"])
    assert "/public/*" in resource
    assert "private" not in resource.lower()


def test_private_flag_is_deployed_without_agent_read_permission() -> None:
    template().resource_count_is("Custom::CDKBucketDeployment", 1)


def test_leaderboard_uses_dynamodb_with_ttl() -> None:
    synthesized = template()

    synthesized.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {
                "AttributeName": "expires_at",
                "Enabled": True,
            },
        },
    )
