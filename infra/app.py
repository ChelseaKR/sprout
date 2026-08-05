#!/usr/bin/env python3
"""CDK app entry point. See infra/README.md for prerequisites and the deploy command."""

from __future__ import annotations

import os

import aws_cdk as cdk
from sprout_stack import SproutServerlessStack

app = cdk.App()
SproutServerlessStack(
    app,
    "SproutServerlessStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
    ),
    description="Sprout — optional serverless chat API (Tier-A observability)",
)

app.synth()
