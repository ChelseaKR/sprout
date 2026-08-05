"""The optional serverless deploy: Lambda (container image) behind an HTTP API, a
monthly budget alarm, and the Tier-A OTel env vars.

Per `STANDARDS/OBSERVABILITY-STANDARD.md` §1, the exporter endpoint/protocol are
environment, not code — every ``OTEL_*`` value here is a Lambda environment variable, and
the application code that reads them lives in ``src/sprout/otel.py`` gated behind
``observability.tier: A``. This stack does not run an OTel Collector itself; ``otlpEndpoint``
must point at one you operate or a vendor that accepts OTLP directly (see infra/README.md).
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as apigwv2_integrations,
)
from aws_cdk import (
    aws_budgets as budgets,
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
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as sns_subscriptions,
)
from constructs import Construct

_SERVICE_NAME = "sprout"


class SproutServerlessStack(Stack):
    """Scale-to-zero Lambda + HTTP API for the optional cloud-generator deployment."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        # Every resource in this stack carries this tag — it is both ordinary cost
        # hygiene and what scopes the budget alarm below to this stack's spend only.
        Tags.of(self).add("Project", _SERVICE_NAME)

        otlp_endpoint = self.node.try_get_context("otlpEndpoint")
        budget_email = self.node.try_get_context("budgetEmail")
        monthly_budget_usd = float(self.node.try_get_context("monthlyBudgetUsd") or 15)
        bedrock_region = self.node.try_get_context("bedrockRegion") or self.region

        log_group = logs.LogGroup(
            self,
            "SproutFunctionLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Tier-A env, per STANDARDS/OBSERVABILITY-STANDARD.md §1. `otel.py` no-ops (and
        # the app still serves) if `observability.tier` is left at its config default of
        # "C" or the OTLP endpoint is unreachable — a telemetry outage never takes the
        # chat API down with it.
        environment: dict[str, str] = {
            "OTEL_SERVICE_NAME": _SERVICE_NAME,
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_PROPAGATORS": "tracecontext,baggage",
            "OTEL_PYTHON_LOG_CORRELATION": "true",
            "SPROUT_GENERATION_REGION": bedrock_region,
        }
        if otlp_endpoint:
            environment["OTEL_EXPORTER_OTLP_ENDPOINT"] = str(otlp_endpoint)

        function = lambda_.DockerImageFunction(
            self,
            "SproutFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                directory="..",
                file="infra/Dockerfile",
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.seconds(29),  # 1s under the HTTP API's 30s hard limit
            environment=environment,
            log_group=log_group,
            description="Sprout chat API (FastAPI via AWS Lambda Web Adapter)",
        )

        # The one network egress a Tier-A deploy needs beyond what the adapter/API GW
        # already grant: Bedrock model invocation, scoped to InvokeModel/InvokeModelWithResponseStream
        # rather than "bedrock:*".
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],  # Bedrock model ARNs are region/account-scoped already
            )
        )

        integration = apigwv2_integrations.HttpLambdaIntegration(
            "SproutIntegration", handler=function
        )
        http_api = apigwv2.HttpApi(
            self,
            "SproutHttpApi",
            default_integration=integration,
            description="Sprout chat API — scale-to-zero (pay per request)",
        )

        if budget_email:
            self._add_budget_alarm(monthly_budget_usd, str(budget_email))

        CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "FunctionName", value=function.function_name)

    def _add_budget_alarm(self, monthly_limit_usd: float, notify_email: str) -> None:
        """A monthly cost budget with alerts at 80% (forecast) and 100% (actual) —
        the "budget alarm" `CLAUDE.md`'s architecture plan calls for. Scoped to this
        stack via a cost-allocation tag rather than the whole account, so it does not
        alarm on unrelated spend.
        """
        topic = sns.Topic(self, "BudgetAlarmTopic", display_name="sprout-budget-alarm")
        topic.add_subscription(sns_subscriptions.EmailSubscription(notify_email))

        notification = budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                notification_type="ACTUAL",
                comparison_operator="GREATER_THAN",
                threshold=100,
                threshold_type="PERCENTAGE",
            ),
            subscribers=[
                budgets.CfnBudget.SubscriberProperty(
                    subscription_type="SNS", address=topic.topic_arn
                )
            ],
        )
        forecast_notification = budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                notification_type="FORECASTED",
                comparison_operator="GREATER_THAN",
                threshold=80,
                threshold_type="PERCENTAGE",
            ),
            subscribers=[
                budgets.CfnBudget.SubscriberProperty(
                    subscription_type="SNS", address=topic.topic_arn
                )
            ],
        )
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=monthly_limit_usd, unit="USD"
                ),
                budget_name=f"{_SERVICE_NAME}-monthly-budget",
                cost_filters={"TagKeyValue": [f"user:Project${_SERVICE_NAME}"]},
            ),
            notifications_with_subscribers=[notification, forecast_notification],
        )
