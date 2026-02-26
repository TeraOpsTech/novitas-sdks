"""
TeraOps CLI — teraops init

Copies SDK files into customer's project directory
and shows setup instructions.
"""
import os
import sys
import shutil


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "init":
        print("Usage: teraops init")
        print("  Copies TeraOps SDK files into your project directory.")
        sys.exit(1)

    project_dir = os.getcwd()
    target_dir = os.path.join(project_dir, "teraops_logging")

    # Check if already exists
    if os.path.exists(target_dir):
        print("teraops_logging/ already exists in this directory.")
        print("Remove it first if you want to reinitialize.")
        sys.exit(1)

    # Copy SDK files from installed package to project directory
    source_dir = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(source_dir, target_dir)

    # Remove cli.py and __pycache__ from the copied files (customer doesn't need these)
    cli_file = os.path.join(target_dir, "cli.py")
    if os.path.exists(cli_file):
        os.remove(cli_file)
    cache_dir = os.path.join(target_dir, "__pycache__")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)

    # Create .env.example
    env_example = os.path.join(project_dir, ".env.example")
    if not os.path.exists(env_example):
        with open(env_example, "w") as f:
            f.write("TERAOPS_API_URL=your_teraops_api_url_here\n")
            f.write("TERAOPS_API_KEY=your_teraops_api_key_here\n")

    # Create README.md with setup instructions
    readme_path = os.path.join(target_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write("""# TeraOps SDK — Setup Guide

## Step 1: Set your credentials

Copy `.env.example` to `.env` and fill in the values TeraOps gave you on signup:

```env
TERAOPS_API_URL=your_teraops_api_url_here
TERAOPS_API_KEY=your_teraops_api_key_here
```

## Step 2: Add these imports to your otel_config.py

```python
import os
from dotenv import load_dotenv
from teraops_logging import attach_teraops

load_dotenv()
```

## Step 3: Add attach_teraops() after your LoggerProvider

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

## Step 4: Install python-dotenv (if not already installed)

```bash
pip3 install python-dotenv
```

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
)
```

## What the SDK does automatically

| Feature | What it does |
|---------|-------------|
| **Auto-enrichment** | Adds `hostname`, `process_id`, `runtime`, `os`, `arch` to every log |
| **Secret redaction** | Scans for passwords, API keys, tokens and replaces with `***REDACTED***` |
| **Size limits** | Truncates messages > 64KB, attribute values > 4KB, max 50 attributes per log |
| **Batched sending** | Buffers logs and sends every 30s in one HTTP call |
| **Retry** | Retries on server errors with exponential backoff |
| **Disk spillover** | If buffer full and API down, logs spill to disk (up to 100MB) |
| **API key validation** | Validates your key on startup — fails fast if invalid |
""")

    print()
    print("  TeraOps SDK initialized successfully!")
    print()
    print("  Created:")
    print(f"    teraops_logging/          — SDK files")
    print(f"    teraops_logging/README.md — setup guide")
    print(f"    .env.example              — add your API URL and key here")
    print()
    print("  -----------------------------------------------")
    print("  Now add this to your otel_config.py:")
    print("  -----------------------------------------------")
    print()
    print("  # Add these imports at the top:")
    print("  import os")
    print("  from dotenv import load_dotenv")
    print("  from teraops_logging import attach_teraops")
    print()
    print("  # Add this after your imports:")
    print("  load_dotenv()")
    print()
    print("  # Add this after your LoggerProvider setup:")
    print("  attach_teraops(")
    print('      logger_provider,')
    print('      api_url=os.getenv("TERAOPS_API_URL"),')
    print('      api_key=os.getenv("TERAOPS_API_KEY"),')
    print("  )")
    print()
    print("  -----------------------------------------------")
    print("  Don't forget:")
    print("  -----------------------------------------------")
    print("  1. Copy .env.example to .env")
    print("  2. Fill in your TERAOPS_API_URL and TERAOPS_API_KEY")
    print("     (provided by TeraOps on signup)")
    print("  3. pip install python-dotenv (if not already installed)")
    print()


if __name__ == "__main__":
    main()
