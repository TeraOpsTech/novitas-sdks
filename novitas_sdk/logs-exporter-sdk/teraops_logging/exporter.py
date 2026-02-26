"""
TeraOps Log Exporter — Collects, filters, and sends logs to TeraOps API

Features:
    - Batched sending (efficient, not per-log)
    - Auto-enrichment (hostname, pid, runtime, os, arch)
    - Secret redaction (passwords, API keys, tokens, AWS keys)
    - Size limits (message, attributes, payload)
    - Disk spillover (when buffer full + API down)
    - API key validation on startup
    - Retry with exponential backoff
    - Clean shutdown with final flush

Usage:
    from teraops_logging.exporter import TeraOpsLogExporter

    exporter = TeraOpsLogExporter(
        api_url="https://back-poc.teraops.ai",
        api_key="your_teraops_api_key",
    )

    processor = SimpleLogRecordProcessor(exporter)
    logger_provider.add_log_record_processor(processor)
"""
import os
import re
import json
import time
import socket
import logging
import platform
import tempfile
import threading
import requests
from typing import Sequence
from datetime import datetime, timezone
from opentelemetry.sdk._logs.export import LogExporter, LogExportResult

from teraops_logging import __version__

logger = logging.getLogger("teraops_exporter")


# ============================================================================
# P0: Secret Redaction Patterns
# ============================================================================
# These regex patterns match common secrets in log messages and attribute values.
# Matched values are replaced with ***REDACTED***
# Customer doesn't configure this — it runs automatically on every log.

_SECRET_PATTERNS = [
    # password=xxx, password: xxx, "password": "xxx"
    re.compile(r'(password\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # api_key=xxx, api-key=xxx, apikey=xxx
    re.compile(r'(api[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # secret_key=xxx, secret-key=xxx, secretkey=xxx
    re.compile(r'(secret[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # access_key=xxx, access-key=xxx
    re.compile(r'(access[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # token=xxx, auth_token=xxx
    re.compile(r'((?:auth[_-]?)?token\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # Authorization: Bearer xxx, Authorization: Basic xxx
    re.compile(r'(authorization\s*[=:]\s*(?:bearer|basic|token)\s+)[^\s,;"\'}\]]+', re.IGNORECASE),
    # Bearer xxx (standalone)
    re.compile(r'(bearer\s+)[A-Za-z0-9_\-\.]+', re.IGNORECASE),
    # AWS_SECRET_ACCESS_KEY=xxx, AWS_ACCESS_KEY_ID=xxx
    re.compile(r'(AWS_[A-Z_]*KEY[_ID]*\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # private_key=xxx, private-key=xxx
    re.compile(r'(private[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # credential=xxx, credentials=xxx
    re.compile(r'(credentials?\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # connection_string=xxx (often has DB passwords)
    re.compile(r'(connection[_-]?string\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # database_url=xxx, db_url=xxx
    re.compile(r'((?:database|db)[_-]?url\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # ssn=xxx, social_security=xxx
    re.compile(r'((?:ssn|social[_-]?security)\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
    # credit_card=xxx, card_number=xxx
    re.compile(r'((?:credit[_-]?card|card[_-]?number)\s*[=:]\s*)[^\s,;"\'}\]]+', re.IGNORECASE),
]

# Field names that should NEVER be sent — these are blocked entirely.
# If a customer sends a log attribute with one of these keys, the value is redacted.
_SENSITIVE_FIELD_NAMES = {
    "password", "passwd", "pwd",
    "secret", "secret_key", "secretkey", "secret-key",
    "api_key", "apikey", "api-key",
    "access_key", "accesskey", "access-key",
    "private_key", "privatekey", "private-key",
    "token", "auth_token", "access_token", "refresh_token",
    "authorization",
    "credential", "credentials",
    "connection_string", "connectionstring",
    "database_url", "db_url",
    "aws_secret_access_key", "aws_access_key_id",
    "ssn", "social_security",
    "credit_card", "card_number", "cvv",
}


# ============================================================================
# P0: Size Limits
# ============================================================================
MAX_MESSAGE_SIZE = 65536          # 64KB per log message
MAX_ATTRIBUTE_VALUE_SIZE = 4096   # 4KB per attribute value
MAX_ATTRIBUTES_PER_LOG = 50       # max fields per log entry
MAX_PAYLOAD_SIZE = 5 * 1024 * 1024  # 5MB per HTTP batch

# P3: Disk Spillover
MAX_DISK_SPILLOVER_SIZE = 100 * 1024 * 1024  # 100MB max disk usage


class TeraOpsLogExporter(LogExporter):
    """
    OTEL Log Exporter for TeraOps.

    Collects logs in a buffer, filters/validates/redacts them,
    and flushes to the TeraOps ingestion API in batches.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        log_type: str = "otel",
        timeout: int = 10,
        batch_interval: int = 30,
        live_logs: bool = False,
        max_buffer_size: int = 10000,
        max_retries: int = 3,
        debug: bool = False,
        use_cloudscraper: bool = False,
        validate_api_key: bool = True,
        spillover_dir: str = None,
    ):
        """
        Args:
            api_url: TeraOps API base URL (e.g. "https://back-poc.teraops.ai")
            api_key: TeraOps API key (provided by TeraOps on signup)
            log_type: Log type identifier sent in X-Log-Type header
            timeout: HTTP request timeout in seconds
            batch_interval: Seconds between batch flushes
            live_logs: If True, sends historical_data=True in payload
            max_buffer_size: Maximum logs to hold in memory buffer
            max_retries: Number of retry attempts on send failure
            debug: If True, logs internal debug messages
            use_cloudscraper: If True, uses cloudscraper to bypass Cloudflare
            validate_api_key: If True, validates API key on startup
            spillover_dir: Directory for disk spillover files (default: system temp)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.log_type = log_type
        self.timeout = timeout
        self.batch_interval = batch_interval
        self.live_logs = live_logs
        self.max_buffer_size = max_buffer_size
        self.max_retries = max_retries
        self.debug = debug
        self.endpoint = f"{self.api_url}/api/ingestion/ingest"

        # Buffer and synchronization
        self._buffer = []
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._shutting_down = False

        # HTTP client — use cloudscraper if needed (for Cloudflare-protected endpoints)
        if use_cloudscraper:
            import cloudscraper
            self.client = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'linux', 'desktop': True}
            )
        else:
            self.client = requests.Session()

        # Collect system info ONCE at startup (auto-enrichment)
        # These fields are added to every log automatically.
        # Customer does nothing — our SDK adds this for free.
        self._system_info = {
            "hostname": socket.gethostname(),
            "process_id": os.getpid(),
            "runtime": f"Python {platform.python_version()}",
            "os": platform.system(),
            "arch": platform.machine(),
        }

        # ---- P3: Disk spillover setup ----
        self._spillover_dir = spillover_dir or tempfile.gettempdir()
        self._spillover_file = os.path.join(self._spillover_dir, f"teraops_spillover_{os.getpid()}.jsonl")

        # ---- P1: SDK version in headers ----
        self._sdk_version = __version__

        # When debug=True, make sure exporter logs are visible on console
        if self.debug:
            logger.setLevel(logging.DEBUG)
            if not logger.handlers:
                _handler = logging.StreamHandler()
                _handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
                logger.addHandler(_handler)

        # ---- P2: API key validation on startup ----
        if validate_api_key:
            self._validate_api_key()

        # Start the background flush loop
        self._shutdown_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._run_flush_loop, daemon=True)
        self._flush_thread.start()

        if self.debug:
            logger.info(
                f"TeraOps SDK v{self._sdk_version} initialized — "
                f"endpoint={self.endpoint}, batch_interval={self.batch_interval}s, "
                f"max_buffer={self.max_buffer_size}"
            )

    # ====================================================================
    # P2: API Key Validation
    # ====================================================================
    def _validate_api_key(self):
        """
        Validate the API key on startup by making a lightweight call.
        Fails fast with a clear error if key is invalid.
        """
        try:
            response = self.client.post(
                self.endpoint,
                json={"logs": []},
                headers=self._build_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 401:
                raise ValueError(
                    f"TeraOps API key is invalid (HTTP 401). "
                    f"Check your api_key and try again."
                )
            elif response.status_code == 403:
                raise ValueError(
                    f"TeraOps API key is forbidden (HTTP 403). "
                    f"Your key may be disabled or expired."
                )

            if self.debug:
                logger.info("API key validated successfully")

        except (requests.ConnectionError, requests.Timeout) as e:
            # Can't reach API — warn but don't block startup
            logger.warning(
                f"Could not validate API key (network error: {e}). "
                f"SDK will start anyway and retry when sending logs."
            )

    # ====================================================================
    # P1: Clean Headers with SDK Version
    # ====================================================================
    def _build_headers(self):
        """Build HTTP headers for API calls."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Log-Type": self.log_type,
            "X-SDK-Version": self._sdk_version,
            "User-Agent": f"teraops-sdk-python/{self._sdk_version}",
            # Cloudflare bypass headers (kept for compatibility)
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.8",
            "Origin": "https://poc.teraops.ai",
            "Referer": "https://poc.teraops.ai/",
            "sec-ch-ua": '"Brave";v="143", "Chromium";v="143"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        return headers

    # ====================================================================
    # P0: Filter — Secret Redaction
    # ====================================================================
    def _redact_secrets(self, text: str) -> str:
        """
        Scan a string for secret patterns and replace matched values
        with ***REDACTED***.

        Example:
            "password=abc123 token=xyz" → "password=***REDACTED*** token=***REDACTED***"
        """
        if not isinstance(text, str):
            return text

        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(r'\1***REDACTED***', text)

        return text

    def _filter_attributes(self, attrs: dict) -> dict:
        """
        Filter log attributes:
        1. Block sensitive field names (value → ***REDACTED***)
        2. Redact secrets in string values
        3. Enforce size limits on values
        4. Enforce max attributes per log
        """
        filtered = {}
        count = 0

        for key, value in attrs.items():
            # Max attributes limit
            if count >= MAX_ATTRIBUTES_PER_LOG:
                if self.debug:
                    logger.warning(
                        f"Log has more than {MAX_ATTRIBUTES_PER_LOG} attributes — "
                        f"extra attributes dropped"
                    )
                break

            # Block sensitive field names
            if key.lower().strip() in _SENSITIVE_FIELD_NAMES:
                filtered[key] = "***REDACTED***"
                count += 1
                continue

            # Redact secrets in string values
            if isinstance(value, str):
                value = self._redact_secrets(value)

                # Enforce attribute value size limit
                if len(value) > MAX_ATTRIBUTE_VALUE_SIZE:
                    value = value[:MAX_ATTRIBUTE_VALUE_SIZE] + "...[TRUNCATED]"

            filtered[key] = value
            count += 1

        return filtered

    # ====================================================================
    # P0: Validate — Check required fields & normalize
    # ====================================================================
    def _validate_and_normalize(self, log_entry: dict) -> dict:
        """
        Validate and normalize a log entry:
        1. Ensure required fields (timestamp, message, severity)
        2. Normalize severity to uppercase
        3. Truncate oversized messages
        4. Redact secrets in message
        """
        # Normalize severity to uppercase
        severity = log_entry.get("severity", "INFO")
        if isinstance(severity, str):
            severity = severity.upper().strip()
        valid_severities = {"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}
        if severity not in valid_severities:
            severity = "INFO"
        log_entry["severity"] = severity

        # Redact secrets in message
        message = log_entry.get("message", "")
        if isinstance(message, str):
            message = self._redact_secrets(message)

            # Enforce message size limit
            if len(message) > MAX_MESSAGE_SIZE:
                message = message[:MAX_MESSAGE_SIZE] + "...[TRUNCATED]"

        log_entry["message"] = message

        return log_entry

    # ====================================================================
    # Core: Flush loop
    # ====================================================================
    def _run_flush_loop(self):
        """Background thread that flushes the buffer at fixed intervals."""
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(timeout=self.batch_interval)
            if not self._shutting_down:
                self._flush()

    def _flush(self):
        """Flush all collected logs to TeraOps in one call."""
        # First check if there are spillover logs on disk to recover
        disk_logs = self._read_spillover()

        with self._lock:
            if not self._buffer and not disk_logs:
                return
            logs = list(self._buffer)
            self._buffer.clear()

        # Disk logs first (older), then buffer logs (newer)
        if disk_logs:
            logs = disk_logs + logs

        if self.debug:
            logger.info(f"Flushing {len(logs)} log(s) to TeraOps")

        self._send(logs)

    # ====================================================================
    # Core: Export (called by OTEL)
    # ====================================================================
    def export(self, batch: Sequence) -> LogExportResult:
        """
        Called by OTEL for every log record.

        Pipeline: Validate → Normalize → Filter → Enrich → Buffer
        """
        if not batch:
            return LogExportResult.SUCCESS

        current_time = datetime.now(timezone.utc)
        current_timestamp_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        for otel_item in batch:
            try:
                log_record = otel_item.log_record if hasattr(otel_item, 'log_record') else otel_item
                attrs = dict(log_record.attributes) if hasattr(log_record, 'attributes') and log_record.attributes else {}

                custom_timestamp = attrs.get("timestamp")

                if custom_timestamp:
                    timestamp = custom_timestamp
                    attrs_copy = {k: v for k, v in attrs.items() if k != "timestamp"}
                else:
                    timestamp = current_timestamp_str
                    attrs_copy = dict(attrs)

                # Step 1: Build log entry with required fields
                log_entry = {
                    "timestamp": timestamp,
                    "message": log_record.body,
                    "severity": log_record.severity_text or "INFO",
                }

                # Step 2: Validate & Normalize (P0)
                log_entry = self._validate_and_normalize(log_entry)

                # Step 3: Auto-enrich with system info (free for customer)
                log_entry.update(self._system_info)

                # Step 4: Filter attributes (P0) — redact secrets, enforce limits
                filtered_attrs = self._filter_attributes(attrs_copy)
                log_entry.update(filtered_attrs)

                # Step 5: Add SDK version
                log_entry["_sdk_version"] = self._sdk_version

                with self._lock:
                    # Drop oldest logs if buffer is full
                    if len(self._buffer) >= self.max_buffer_size:
                        # P3: Spill to disk instead of dropping
                        overflow = self._buffer[:1000]
                        self._write_spillover(overflow)
                        self._buffer = self._buffer[1000:]

                        if self.debug:
                            logger.warning(
                                f"Buffer full — spilled {len(overflow)} log(s) to disk"
                            )

                    self._buffer.append(log_entry)

            except Exception as e:
                logger.error(f"Error processing log record: {e}")
                continue

        return LogExportResult.SUCCESS

    # ====================================================================
    # Core: Send to TeraOps API
    # ====================================================================
    def _send(self, logs: list):
        """Send logs to TeraOps API with retry on failure."""
        if not logs:
            return

        headers = self._build_headers()

        # P0: Enforce max payload size — split into chunks if needed
        chunks = self._split_by_payload_size(logs)

        with self._send_lock:
            for chunk in chunks:
                self._send_chunk(chunk, headers)

    def _send_chunk(self, logs: list, headers: dict):
        """Send a single chunk of logs."""
        payload = {"logs": logs}
        if self.live_logs:
            payload["historical_data"] = True

        for attempt in range(self.max_retries):
            try:
                response = self.client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    if self.debug:
                        logger.info(f"Sent {len(logs)} log(s) — response: {response.json()}")
                    return

                # Server error — retry
                if response.status_code >= 500:
                    wait = 2 ** attempt
                    if self.debug:
                        logger.warning(
                            f"Send failed (HTTP {response.status_code}), "
                            f"retry {attempt + 1}/{self.max_retries} in {wait}s"
                        )
                    time.sleep(wait)
                    continue

                # Client error (4xx) — don't retry, won't help
                logger.error(f"Send failed (HTTP {response.status_code}): {response.text}")
                return

            except Exception as e:
                wait = 2 ** attempt
                if attempt < self.max_retries - 1:
                    if self.debug:
                        logger.warning(f"Send error: {e}, retry {attempt + 1}/{self.max_retries} in {wait}s")
                    time.sleep(wait)
                else:
                    logger.error(f"Send failed after {self.max_retries} retries: {e}")

        # All retries exhausted — spill to disk (P3)
        self._write_spillover(logs)
        if self.debug:
            logger.info(f"Retries exhausted — spilled {len(logs)} log(s) to disk")

    # ====================================================================
    # P0: Payload Size Splitting
    # ====================================================================
    def _split_by_payload_size(self, logs: list) -> list:
        """
        Split logs into chunks that fit within MAX_PAYLOAD_SIZE.
        Each chunk will be sent in a separate HTTP call.
        """
        chunks = []
        current_chunk = []
        current_size = 0

        for log in logs:
            # Estimate JSON size of this log entry
            log_size = len(json.dumps(log, default=str))

            if current_size + log_size > MAX_PAYLOAD_SIZE and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0

            current_chunk.append(log)
            current_size += log_size

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    # ====================================================================
    # P3: Disk Spillover
    # ====================================================================
    def _write_spillover(self, logs: list):
        """
        Write overflow logs to disk when buffer is full or send fails.
        Appends to a JSONL file. Respects MAX_DISK_SPILLOVER_SIZE.
        """
        try:
            # Check current spillover file size
            current_size = 0
            if os.path.exists(self._spillover_file):
                current_size = os.path.getsize(self._spillover_file)

            if current_size >= MAX_DISK_SPILLOVER_SIZE:
                if self.debug:
                    logger.warning(
                        f"Disk spillover limit reached ({MAX_DISK_SPILLOVER_SIZE // (1024*1024)}MB) "
                        f"— dropping {len(logs)} log(s)"
                    )
                return

            with open(self._spillover_file, 'a') as f:
                for log in logs:
                    line = json.dumps(log, default=str)
                    f.write(line + '\n')

            if self.debug:
                logger.info(f"Wrote {len(logs)} log(s) to disk spillover: {self._spillover_file}")

        except Exception as e:
            logger.error(f"Disk spillover write failed: {e}")

    def _read_spillover(self) -> list:
        """
        Read and clear spillover logs from disk.
        Returns list of log entries recovered from disk.
        """
        if not os.path.exists(self._spillover_file):
            return []

        try:
            file_size = os.path.getsize(self._spillover_file)
            if file_size == 0:
                return []

            logs = []
            with open(self._spillover_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            logs.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            # Clear the spillover file after reading
            os.remove(self._spillover_file)

            if self.debug and logs:
                logger.info(f"Recovered {len(logs)} log(s) from disk spillover")

            return logs

        except Exception as e:
            logger.error(f"Disk spillover read failed: {e}")
            return []

    # ====================================================================
    # Core: Shutdown
    # ====================================================================
    def shutdown(self):
        """Stop the flush loop and send any remaining logs."""
        self._shutting_down = True
        self._shutdown_event.set()
        self._flush_thread.join(timeout=5)

        # Wait for any in-progress send to finish
        self._send_lock.acquire()
        self._send_lock.release()

        # Final flush
        with self._lock:
            if self._buffer:
                logs = list(self._buffer)
                self._buffer.clear()
            else:
                logs = []

        if logs:
            if self.debug:
                logger.info(f"Shutdown — flushing {len(logs)} remaining log(s)")
            self._send(logs)

        if self.debug:
            logger.info("TeraOps SDK shutdown complete")

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush buffer immediately."""
        self._flush()
        return True
