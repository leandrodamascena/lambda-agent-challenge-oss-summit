import os

from aws_lambda_powertools import Logger, Metrics, Tracer

service_name = os.getenv("POWERTOOLS_SERVICE_NAME", "break-my-agent")
metrics_namespace = os.getenv("POWERTOOLS_METRICS_NAMESPACE", "BreakMyAgent")

logger = Logger(service=service_name)
tracer = Tracer(service=service_name)
metrics = Metrics(namespace=metrics_namespace, service=service_name)
