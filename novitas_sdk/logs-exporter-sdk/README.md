# TeraOps Log Exporter SDK

OpenTelemetry Log Exporter for the TeraOps observability platform.

Plugs into your existing OTEL setup with **one line of code**. Your existing exporters (Datadog, New Relic, Console, etc.) keep working — TeraOps is added alongside.

## Installation

```bash
pip install git+https://github.com/TeraOpsTech/Teraops-sdks.git#subdirectory=logs-exporter-sdk
```

## Quick Start

### 1. Get your API key

Sign up at [teraops.ai](https://teraops.ai) to get your API key. Add it to your `.env`:

```env
TERAOPS_API_KEY=your_teraops_api_key_here
TERAOPS_API_URL=https://back-poc.teraops.ai
```

### 2. Connect to your OTEL setup

If you already have an OTEL LoggerProvider, just add one line:

```python
from teraops_logging import attach_teraops

# Your existing OTEL setup (unchanged)
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(SimpleLogRecordProcessor(ConsoleLogExporter()))

# Add TeraOps — one line
attach_teraops(
    logger_provider,
    api_key=os.getenv("TERAOPS_API_KEY"),
)
```

### 3. Full example with OTEL from scratch

```python
import os
import logging
from dotenv import load_dotenv
from opentelemetry.sdk.resources import Resource
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, ConsoleLogExporter
from teraops_logging import attach_teraops

load_dotenv()

# Step 1: Create OTEL LoggerProvider
resource = Resource.create({"service.name": "my-app"})
logger_provider = LoggerProvider(resource=resource)

# Step 2: Add your exporters (Console, Datadog, New Relic, etc.)
logger_provider.add_log_record_processor(
    SimpleLogRecordProcessor(ConsoleLogExporter())
)

# Step 3: Add TeraOps (one line)
attach_teraops(
    logger_provider,
    api_key=os.getenv("TERAOPS_API_KEY"),
    api_url=os.getenv("TERAOPS_API_URL", "https://back-poc.teraops.ai"),
)

# Step 4: Set as global provider
set_logger_provider(logger_provider)

# Step 5: Bridge Python logging to OTEL
handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

# Step 6: Log normally — TeraOps receives everything automatically
logger = logging.getLogger("my-app")
logger.info("Application started")
logger.info("Processing request", extra={"user_id": "123", "endpoint": "/api/process"})
```

## What the SDK does automatically

You don't configure any of this — it just works:

| Feature | What it does |
|---------|-------------|
| **Auto-enrichment** | Adds `hostname`, `process_id`, `runtime`, `os`, `arch` to every log |
| **Secret redaction** | Scans for passwords, API keys, tokens, AWS keys and replaces with `***REDACTED***` |
| **Size limits** | Truncates messages > 64KB, attribute values > 4KB, max 50 attributes per log |
| **Batched sending** | Buffers logs and sends every 30s in one HTTP call (not per-log) |
| **Retry** | Retries on server errors with exponential backoff |
| **Disk spillover** | If buffer is full and API is down, logs spill to disk (up to 100MB) and recover when API comes back |
| **API key validation** | Validates your key on startup — fails fast if invalid |
| **Payload splitting** | Splits large batches into 5MB chunks automatically |

## Configuration options

```python
attach_teraops(
    logger_provider,                          # required — your OTEL LoggerProvider
    api_key="your_key",                       # required — TeraOps API key
    api_url="https://back-poc.teraops.ai",    # optional — API URL (default: back-poc)
    log_type="otel",                          # optional — log type identifier
    live_logs=False,                          # optional — True for real-time ingestion
    debug=False,                              # optional — True to see SDK debug logs
    validate_api_key=True,                    # optional — validate key on startup
    spillover_dir=None,                       # optional — disk spillover directory
)
```

## Secret redaction examples

The SDK automatically redacts secrets before sending:

```
# Input log message:
"Connecting with password=abc123 and token=xyz789"

# What TeraOps receives:
"Connecting with password=***REDACTED*** and token=***REDACTED***"
```

```
# Input log attributes:
{"api_key": "sk-12345", "user_id": "123"}

# What TeraOps receives:
{"api_key": "***REDACTED***", "user_id": "123"}
```

Patterns redacted: `password`, `api_key`, `secret_key`, `access_key`, `token`, `authorization`, `Bearer`, `AWS_*_KEY`, `private_key`, `credential`, `connection_string`, `database_url`, `ssn`, `credit_card`

## How it works

```
Your App (Python logging)
    │
    ▼
OTEL LoggingHandler (bridge)
    │
    ▼
OTEL LoggerProvider
    ├── Your exporters (Console, Datadog, New Relic, etc.)
    │
    └── TeraOps SDK
            │
            ├── Validate & Normalize (severity, timestamp)
            ├── Auto-enrich (hostname, pid, runtime, os, arch)
            ├── Filter (redact secrets, enforce size limits)
            ├── Buffer (in memory, max 10,000 logs)
            │       └── Disk spillover (if buffer full, up to 100MB)
            │
            └── Send (batched every 30s, retry with backoff)
                    │
                    ▼
              TeraOps API → S3 storage
```

## Requirements

- Python >= 3.8
- `opentelemetry-api >= 1.20.0`
- `opentelemetry-sdk >= 1.20.0`
- `requests >= 2.28.0`

## Version

Current: **v0.1.0**

SDK version is sent in every request header (`X-SDK-Version`) for debugging.
