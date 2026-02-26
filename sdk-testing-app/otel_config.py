"""
OTEL Setup — Customer's existing OpenTelemetry config

This is what a customer already has before TeraOps.
Logs go to stdout (ConsoleLogExporter) only.
"""
import logging
from opentelemetry.sdk.resources import Resource
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, ConsoleLogExporter


def setup_otel():
    # Step 1: Resource
    resource = Resource.create({"service.name": "sdk-testing-app"})

    # Step 2: LoggerProvider
    logger_provider = LoggerProvider(resource=resource)

    # Step 3: Console exporter — logs to stdout
    logger_provider.add_log_record_processor(
        SimpleLogRecordProcessor(ConsoleLogExporter())
    )

    # Step 4: Set global + bridge Python logging
    set_logger_provider(logger_provider)
    handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    return logger_provider
