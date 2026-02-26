"""
OTEL Setup — Customer's existing OpenTelemetry config

This is what a customer already has.
TeraOps SDK is added via pip install, then one line: attach_teraops()
"""
import os
import logging
from dotenv import load_dotenv
from opentelemetry.sdk.resources import Resource
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, ConsoleLogExporter
from teraops_logging import attach_teraops

load_dotenv()


def setup_otel():
    # Step 1: Resource
    resource = Resource.create({"service.name": "sdk-testing-app"})

    # Step 2: LoggerProvider
    logger_provider = LoggerProvider(resource=resource)

    # Step 3: Console exporter (customer's own)
    logger_provider.add_log_record_processor(
        SimpleLogRecordProcessor(ConsoleLogExporter())
    )

    # Step 4: TeraOps SDK (installed via pip) — one line
    attach_teraops(
        logger_provider,
        api_url=os.getenv("TERAOPS_API_URL"),
        api_key=os.getenv("TERAOPS_API_KEY"),
    )

    # Step 5: Set global + bridge Python logging
    set_logger_provider(logger_provider)
    handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    return logger_provider
