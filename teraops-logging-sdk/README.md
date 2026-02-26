# TeraOps Log Exporter SDK

OpenTelemetry Log Exporter for the TeraOps observability platform.

Plugs into your existing OTEL setup. Your existing exporters (Datadog, New Relic, Console, etc.) keep working — TeraOps is added alongside.

## Installation

```bash
pip3 install git+https://github.com/TeraOpsTech/novitas-sdks.git#subdirectory=teraops-logging-sdk
```

## Setup

After installing, run this inside your project folder:

```bash
teraops init
```

This will:
- Copy `teraops_logging/` folder into your project (visible, not hidden in venv)
- Create `.env.example` with the required variables
- Print exactly what to add to your code

## Quick Start

### Step 1: Set your credentials

Copy `.env.example` to `.env` and fill in the values TeraOps gave you on signup:

```env
TERAOPS_API_URL=your_teraops_api_url_here
TERAOPS_API_KEY=your_teraops_api_key_here
```

### Step 2: Add these imports to your otel_config.py

```python
import os
from dotenv import load_dotenv
from teraops_logging import attach_teraops

load_dotenv()
```

### Step 3: Add attach_teraops() after your LoggerProvider

```python
# Your existing OTEL setup (unchanged)
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    SimpleLogRecordProcessor(ConsoleLogExporter())
)

# Add TeraOps — paste this after your existing exporters
attach_teraops(
    logger_provider,
    api_url=os.getenv("TERAOPS_API_URL"),
    api_key=os.getenv("TERAOPS_API_KEY"),
)
```

### Step 4: Install python-dotenv (if not already installed)

```bash
pip3 install python-dotenv
```

That's it. Your existing stdout/console logs keep working. TeraOps now receives a copy of every log automatically.

## What you need to add (summary)

| What | Where |
|------|-------|
| `import os` | top of otel_config.py |
| `from dotenv import load_dotenv` | top of otel_config.py |
| `from teraops_logging import attach_teraops` | top of otel_config.py |
| `load_dotenv()` | before setup_otel() function |
| `attach_teraops(logger_provider, api_url=..., api_key=...)` | after your LoggerProvider setup |
| `TERAOPS_API_URL=...` | .env file |
| `TERAOPS_API_KEY=...` | .env file |

## Configuration options

```python
attach_teraops(
    logger_provider,                          # required — your OTEL LoggerProvider
    api_url="your_api_url",                   # required — TeraOps API URL (provided on signup)
    api_key="your_api_key",                   # required — TeraOps API key (provided on signup)
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
- `python-dotenv` (for loading .env file)

## Version

Current: **v0.1.0**
