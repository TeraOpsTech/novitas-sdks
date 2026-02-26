"""
TeraOps SDK — OpenTelemetry Log Exporter for TeraOps

Usage:
    pip install teraops-sdk

    from teraops_logging import attach_teraops
    attach_teraops(logger_provider, api_key="your_key")
"""

__version__ = "0.1.0"

from teraops_logging.config import attach_teraops
from teraops_logging.exporter import TeraOpsLogExporter

__all__ = ["attach_teraops", "TeraOpsLogExporter", "__version__"]
