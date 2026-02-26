"""
TeraOps Config — Attach TeraOps exporter to your existing OTEL setup

This is all the customer needs to do:

    from teraops_logging import attach_teraops

    attach_teraops(
        logger_provider,
        api_key=os.getenv("TERAOPS_API_KEY"),
    )

That's it. One function call. Everything else is automatic:
    - Logs are buffered and sent in batches
    - Secrets are redacted before sending
    - System info (hostname, pid, etc.) is auto-enriched
    - Oversized messages are truncated
    - If API is down, logs spill to disk
"""
from teraops_logging.exporter import TeraOpsLogExporter
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor


def attach_teraops(
    logger_provider,
    api_key: str,
    api_url: str = "https://back-poc.teraops.ai",
    log_type: str = "otel",
    live_logs: bool = False,
    debug: bool = False,
    use_cloudscraper: bool = False,
    validate_api_key: bool = True,
    spillover_dir: str = None,
):
    """
    Attach TeraOps exporter to your existing OTEL LoggerProvider.

    Your existing exporters (Datadog, New Relic, Console, etc.) keep working.
    TeraOps is added alongside — both get every log.

    Args:
        logger_provider: Your existing OTEL LoggerProvider
        api_key: TeraOps API key (provided by TeraOps on signup)
        api_url: TeraOps API base URL
        log_type: Log type identifier
        live_logs: If True, sends historical_data=True
        debug: If True, shows SDK debug logs in console
        use_cloudscraper: If True, uses cloudscraper for Cloudflare
        validate_api_key: If True, validates API key on startup
        spillover_dir: Directory for disk spillover (default: system temp)

    Returns:
        TeraOpsLogExporter instance (for advanced use, most customers ignore this)
    """
    exporter = TeraOpsLogExporter(
        api_url=api_url,
        api_key=api_key,
        log_type=log_type,
        live_logs=live_logs,
        debug=debug,
        use_cloudscraper=use_cloudscraper,
        validate_api_key=validate_api_key,
        spillover_dir=spillover_dir,
    )

    processor = SimpleLogRecordProcessor(exporter)
    logger_provider.add_log_record_processor(processor)

    return exporter
