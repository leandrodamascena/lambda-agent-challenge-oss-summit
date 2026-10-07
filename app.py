#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from infra.osso_stack import OssoStack

app = cdk.App()
target_account = app.node.try_get_context("targetAccount") or os.getenv("CDK_DEFAULT_ACCOUNT")
target_region = app.node.try_get_context("targetRegion") or os.getenv(
    "CDK_DEFAULT_REGION", "eu-west-1"
)

OssoStack(
    app,
    "BreakMyAgentStack",
    model_id=app.node.try_get_context("modelId") or "global.openai.gpt-6-astra",
    env=cdk.Environment(
        account=target_account,
        region=target_region,
    ),
)

app.synth()
