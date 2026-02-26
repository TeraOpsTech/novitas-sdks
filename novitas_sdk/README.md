# TeraOps Log Exporter SDK

OpenTelemetry Log Exporter for the TeraOps observability platform.

Plugs into your existing OTEL setup with **one line of code**. Your existing exporters (Datadog, New Relic, Console, etc.) keep working — TeraOps is added alongside.

## Installation

```bash
pip3 install git+https://github.com/TeraOpsTech/novitas-sdks.git
```

## Quick Start

### 1. Set your API key

Add your TeraOps API key to your `.env`:

```env
TERAOPS_API_KEY=your_teraops_api_key_here
```

### 2. Attach to your existing OTEL LoggerProvider

```python
import os
from teraops_logging import attach_teraops

# Your existing logger_provider (however you created it)
attach_teraops(
    logger_provider,
    api_key=os.getenv("TERAOPS_API_KEY"),
)
```

That's it. One import, one function call. Your existing OTEL setup stays unchanged.

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

## Secret redaction

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
              TeraOps API
```

## Requirements

- Python >= 3.8
- `opentelemetry-api >= 1.20.0`
- `opentelemetry-sdk >= 1.20.0`
- `requests >= 2.28.0`

## Version

Current: **v0.1.0**
