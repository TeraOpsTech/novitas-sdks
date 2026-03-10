<?php

declare(strict_types=1);

namespace TeraOps\Logging;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\RequestException;
use OpenTelemetry\SDK\Logs\LogRecordExporterInterface;
use OpenTelemetry\SDK\Logs\ReadableLogRecord;
use OpenTelemetry\SDK\Common\Future\CancellationInterface;
use OpenTelemetry\SDK\Common\Future\FutureInterface;
use OpenTelemetry\SDK\Common\Future\CompletedFuture;

/**
 * TeraOps Log Exporter for OpenTelemetry PHP
 *
 * Collects logs in a buffer, filters/validates/redacts them,
 * and flushes to the TeraOps ingestion API in batches.
 *
 * Features:
 *   - Batched sending (efficient, not per-log)
 *   - Auto-enrichment (hostname, pid, runtime, os, arch)
 *   - Secret redaction (passwords, API keys, tokens, AWS keys)
 *   - Size limits (message, attributes, payload)
 *   - API key validation on startup
 *   - Retry with exponential backoff
 *   - Format tagging (_formatted, _format_issues)
 */
class TeraOpsLogExporter implements LogRecordExporterInterface
{
    private const SDK_VERSION = '0.1.0';

    // Size Limits
    private const MAX_MESSAGE_SIZE = 65536;         // 64KB per log message
    private const MAX_ATTRIBUTE_VALUE_SIZE = 4096;  // 4KB per attribute value
    private const MAX_ATTRIBUTES_PER_LOG = 50;      // max fields per log entry
    private const MAX_PAYLOAD_SIZE = 5242880;       // 5MB per HTTP batch
    private const MAX_DISK_SPILLOVER_SIZE = 104857600; // 100MB disk spillover cap

    // Sensitive field names — values are always redacted
    private const SENSITIVE_FIELD_NAMES = [
        'password', 'passwd', 'pwd',
        'secret', 'secret_key', 'secretkey', 'secret-key',
        'api_key', 'apikey', 'api-key',
        'access_key', 'accesskey', 'access-key',
        'private_key', 'privatekey', 'private-key',
        'authorization',
        'credential', 'credentials',
        'connection_string', 'connectionstring',
        'database_url', 'db_url',
        'aws_secret_access_key', 'aws_access_key_id',
        'ssn', 'social_security',
        'credit_card', 'card_number', 'cvv',
    ];

    private string $apiUrl;
    private string $apiKey;
    private string $logType;
    private int $timeout;
    private bool $liveLogs;
    private int $maxBufferSize;
    private int $maxRetries;
    private bool $debug;
    private string $endpoint;

    private int $batchInterval;
    private float $lastFlushTime;
    private string $spilloverFile;

    private Client $client;
    private array $buffer = [];
    private array $systemInfo;
    private bool $shuttingDown = false;

    /** @var string[] Secret redaction regex patterns */
    private array $secretPatterns;

    public function __construct(
        string $apiUrl,
        string $apiKey,
        string $logType = 'otel',
        int $timeout = 10,
        bool $liveLogs = false,
        int $maxBufferSize = 10000,
        int $maxRetries = 3,
        bool $debug = false,
        bool $validateApiKey = true,
        int $batchInterval = 30,
        string $spilloverDir = '',
        string $proxy = '',
    ) {
        if (empty($apiKey)) {
            throw new \InvalidArgumentException('TeraOps api_key is required');
        }
        if (empty($apiUrl)) {
            throw new \InvalidArgumentException('TeraOps api_url is required');
        }

        $this->apiUrl = rtrim($apiUrl, '/');
        $this->apiKey = $apiKey;
        $this->logType = $logType;
        $this->timeout = $timeout;
        $this->liveLogs = $liveLogs;
        $this->maxBufferSize = $maxBufferSize;
        $this->maxRetries = $maxRetries;
        $this->debug = $debug;
        $this->endpoint = $this->apiUrl . '/api/ingestion/ingest';
        $this->batchInterval = $batchInterval;
        $this->lastFlushTime = microtime(true);

        // Disk spillover
        $spillDir = $spilloverDir !== '' ? $spilloverDir : sys_get_temp_dir();
        $this->spilloverFile = $spillDir . '/teraops_spillover_' . getmypid() . '.jsonl';

        // HTTP client
        $clientOptions = ['timeout' => $this->timeout];
        if ($proxy !== '') {
            $clientOptions['proxy'] = $proxy;
        }
        $this->client = new Client($clientOptions);

        // System info — collected once at startup
        $this->systemInfo = [
            'hostname' => gethostname() ?: 'unknown',
            'process_id' => getmypid() ?: 0,
            'runtime' => 'PHP ' . PHP_VERSION,
            'os' => PHP_OS_FAMILY,
            'arch' => php_uname('m'),
        ];

        // Compile secret patterns
        $this->secretPatterns = [
            '/(password\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(api[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(secret[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(access[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(authorization\s*[=:]\s*(?:bearer|basic|token)\s+)[^\s,;"\'}\]]+/i',
            '/(bearer\s+)[A-Za-z0-9_\-\.]+/i',
            '/(AWS_[A-Z_]*KEY[_ID]*\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(private[_-]?key\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(credentials?\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/(connection[_-]?string\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/((?:database|db)[_-]?url\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/((?:ssn|social[_-]?security)\s*[=:]\s*)[^\s,;"\'}\]]+/i',
            '/((?:credit[_-]?card|card[_-]?number)\s*[=:]\s*)[^\s,;"\'}\]]+/i',
        ];

        // Validate API key on startup
        if ($validateApiKey) {
            $this->validateApiKey();
        }

        // Flush buffer when PHP request ends
        register_shutdown_function([$this, 'shutdown']);

        if ($this->debug) {
            error_log(sprintf(
                'TeraOps SDK v%s initialized — endpoint=%s, max_buffer=%d, batch_interval=%ds, spillover=%s',
                self::SDK_VERSION,
                $this->endpoint,
                $this->maxBufferSize,
                $this->batchInterval,
                $this->spilloverFile
            ));
        }
    }

    // ================================================================
    // API Key Validation
    // ================================================================
    private function validateApiKey(): void
    {
        try {
            $response = $this->client->post($this->endpoint, [
                'json' => ['logs' => []],
                'headers' => $this->buildHeaders(),
            ]);

            if ($this->debug) {
                error_log('TeraOps: API key validated successfully');
            }
        } catch (RequestException $e) {
            $code = $e->hasResponse() ? $e->getResponse()->getStatusCode() : 0;

            if ($code === 401) {
                throw new \RuntimeException(
                    'TeraOps API key is invalid (HTTP 401). Check your api_key and try again.'
                );
            }
            if ($code === 403) {
                throw new \RuntimeException(
                    'TeraOps API key is forbidden (HTTP 403). Your key may be disabled or expired.'
                );
            }

            // Network error — warn but don't block startup
            if ($this->debug) {
                error_log('TeraOps: Could not validate API key (network error). SDK will retry when sending logs.');
            }
        }
    }

    // ================================================================
    // HTTP Headers
    // ================================================================
    private function buildHeaders(): array
    {
        return [
            'Authorization' => 'Bearer ' . $this->apiKey,
            'Content-Type' => 'application/json',
            'X-Log-Type' => $this->logType,
            'X-SDK-Version' => self::SDK_VERSION,
            'User-Agent' => 'teraops-sdk-php/' . self::SDK_VERSION,
            // Cloudflare bypass headers (match browser request pattern)
            'Accept' => '*/*',
            'Accept-Language' => 'en-US,en;q=0.8',
            'Origin' => 'https://poc.teraops.ai',
            'Referer' => 'https://poc.teraops.ai/',
            'sec-ch-ua' => '"Brave";v="143", "Chromium";v="143"',
            'sec-ch-ua-mobile' => '?0',
            'sec-ch-ua-platform' => '"Linux"',
            'sec-fetch-dest' => 'empty',
            'sec-fetch-mode' => 'cors',
            'sec-fetch-site' => 'same-site',
        ];
    }

    // ================================================================
    // Secret Redaction
    // ================================================================
    private function redactSecrets(string $text): string
    {
        foreach ($this->secretPatterns as $pattern) {
            $text = preg_replace($pattern, '$1***REDACTED***', $text);
        }
        return $text;
    }

    /**
     * Filter log attributes:
     * 1. Block sensitive field names
     * 2. Redact secrets in string values
     * 3. Enforce size limits
     *
     * @return array{0: array, 1: string[]} [filtered_attrs, format_issues]
     */
    private function filterAttributes(array $attrs): array
    {
        $filtered = [];
        $issues = [];
        $count = 0;

        foreach ($attrs as $key => $value) {
            if ($count >= self::MAX_ATTRIBUTES_PER_LOG) {
                if (!in_array('attributes_dropped', $issues)) {
                    $issues[] = 'attributes_dropped';
                }
                break;
            }

            // Block sensitive field names
            if (in_array(strtolower(trim($key)), self::SENSITIVE_FIELD_NAMES)) {
                $filtered[$key] = '***REDACTED***';
                if (!in_array('secrets_redacted', $issues)) {
                    $issues[] = 'secrets_redacted';
                }
                $count++;
                continue;
            }

            // Redact secrets in string values
            if (is_string($value)) {
                $redacted = $this->redactSecrets($value);
                if ($redacted !== $value && !in_array('secrets_redacted', $issues)) {
                    $issues[] = 'secrets_redacted';
                }
                $value = $redacted;

                // Enforce attribute value size limit
                if (strlen($value) > self::MAX_ATTRIBUTE_VALUE_SIZE) {
                    $value = substr($value, 0, self::MAX_ATTRIBUTE_VALUE_SIZE) . '...[TRUNCATED]';
                    if (!in_array('attribute_truncated', $issues)) {
                        $issues[] = 'attribute_truncated';
                    }
                }
            }

            $filtered[$key] = $value;
            $count++;
        }

        return [$filtered, $issues];
    }

    // ================================================================
    // Validate & Normalize
    // ================================================================

    /**
     * @return array{0: array, 1: string[]} [log_entry, format_issues]
     */
    private function validateAndNormalize(array $logEntry): array
    {
        $issues = [];

        // Normalize severity
        $severity = $logEntry['severity'] ?? 'INFO';
        if (is_string($severity)) {
            $severity = strtoupper(trim($severity));
        }
        $validSeverities = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'FATAL', 'CRITICAL'];
        if (!in_array($severity, $validSeverities)) {
            $severity = 'INFO';
            $issues[] = 'invalid_severity';
        }
        $logEntry['severity'] = $severity;

        // Check for missing message
        $message = $logEntry['message'] ?? '';
        if (empty($message) || (is_string($message) && trim($message) === '')) {
            $issues[] = 'missing_message';
        }

        // Redact secrets in message
        if (is_string($message)) {
            $redacted = $this->redactSecrets($message);
            if ($redacted !== $message) {
                $issues[] = 'secrets_redacted_in_message';
            }
            $message = $redacted;

            // Enforce message size limit
            if (strlen($message) > self::MAX_MESSAGE_SIZE) {
                $message = substr($message, 0, self::MAX_MESSAGE_SIZE) . '...[TRUNCATED]';
                $issues[] = 'message_truncated';
            }
        }
        $logEntry['message'] = $message;

        return [$logEntry, $issues];
    }

    // ================================================================
    // Export (called by OTEL for every log record)
    // ================================================================
    public function export(iterable $batch, ?CancellationInterface $cancellation = null): FutureInterface
    {
        $currentTimestamp = gmdate('Y-m-d\TH:i:s\Z');

        foreach ($batch as $record) {
            try {
                // Extract attributes
                $attrs = [];
                if (method_exists($record, 'getAttributes')) {
                    $attributes = $record->getAttributes();
                    if ($attributes !== null) {
                        $attrs = $attributes->toArray();
                    }
                }

                // Check for custom timestamp
                $timestamp = $attrs['timestamp'] ?? $currentTimestamp;
                unset($attrs['timestamp']);

                // Step 1: Build log entry
                $logEntry = [
                    'timestamp' => $timestamp,
                    'message' => $record->getBody() ?? '',
                    'severity' => $record->getSeverityText() ?? 'INFO',
                ];

                // Step 2: Validate & Normalize
                [$logEntry, $validateIssues] = $this->validateAndNormalize($logEntry);

                // Step 3: Auto-enrich with system info
                $logEntry = array_merge($logEntry, $this->systemInfo);

                // Step 4: Filter attributes
                [$filteredAttrs, $filterIssues] = $this->filterAttributes($attrs);
                $logEntry = array_merge($logEntry, $filteredAttrs);

                // Step 5: Add SDK version
                $logEntry['_sdk_version'] = self::SDK_VERSION;

                // Step 6: Format status tag
                $allIssues = array_merge($validateIssues, $filterIssues);
                $logEntry['_formatted'] = empty($allIssues);
                $logEntry['_format_issues'] = $allIssues;

                // Add to buffer
                if (count($this->buffer) >= $this->maxBufferSize) {
                    // Buffer full — spill oldest 1000 logs to disk, then flush remainder
                    $spillCount = min(1000, count($this->buffer));
                    $spillLogs = array_splice($this->buffer, 0, $spillCount);
                    $this->writeSpillover($spillLogs);
                    $this->flush();
                }
                $this->buffer[] = $logEntry;

            } catch (\Throwable $e) {
                if ($this->debug) {
                    error_log('TeraOps: Error processing log record: ' . $e->getMessage());
                }
                continue;
            }
        }

        // Auto-flush if batchInterval has elapsed
        if (microtime(true) - $this->lastFlushTime >= $this->batchInterval) {
            $this->flush();
        }

        return new CompletedFuture(true);
    }

    // ================================================================
    // Flush & Send
    // ================================================================
    private function flush(): void
    {
        $this->lastFlushTime = microtime(true);

        // Recover any logs spilled to disk from previous failures
        $diskLogs = $this->readSpillover();

        if (empty($this->buffer) && empty($diskLogs)) {
            return;
        }

        $logs = array_merge($diskLogs, $this->buffer);
        $this->buffer = [];

        if ($this->debug) {
            $diskCount = count($diskLogs);
            error_log(sprintf(
                'TeraOps: Flushing %d log(s)%s',
                count($logs),
                $diskCount > 0 ? sprintf(' (including %d recovered from disk)', $diskCount) : ''
            ));
        }

        $this->send($logs);
    }

    private function send(array $logs): void
    {
        if (empty($logs)) {
            return;
        }

        $headers = $this->buildHeaders();
        $chunks = $this->splitByPayloadSize($logs);

        foreach ($chunks as $chunk) {
            $this->sendChunk($chunk, $headers);
        }
    }

    private function sendChunk(array $logs, array $headers): void
    {
        $payload = ['logs' => $logs];
        if ($this->liveLogs) {
            $payload['historical_data'] = true;
        }

        for ($attempt = 0; $attempt < $this->maxRetries; $attempt++) {
            try {
                $response = $this->client->post($this->endpoint, [
                    'json' => $payload,
                    'headers' => $headers,
                ]);

                $statusCode = $response->getStatusCode();

                if ($statusCode === 200) {
                    if ($this->debug) {
                        $body = json_decode($response->getBody()->getContents(), true);
                        error_log(sprintf('TeraOps: Sent %d log(s) — response: %s', count($logs), json_encode($body)));
                    }
                    return;
                }

                // Server error — retry
                if ($statusCode >= 500) {
                    $wait = pow(2, $attempt);
                    if ($this->debug) {
                        error_log(sprintf(
                            'TeraOps: Send failed (HTTP %d), retry %d/%d in %ds',
                            $statusCode, $attempt + 1, $this->maxRetries, $wait
                        ));
                    }
                    sleep($wait);
                    continue;
                }

                // Client error (4xx) — don't retry
                if ($this->debug) {
                    error_log(sprintf('TeraOps: Send failed (HTTP %d): %s', $statusCode, $response->getBody()->getContents()));
                }
                return;

            } catch (\Throwable $e) {
                $wait = pow(2, $attempt);
                if ($attempt < $this->maxRetries - 1) {
                    if ($this->debug) {
                        error_log(sprintf('TeraOps: Send error: %s, retry %d/%d in %ds', $e->getMessage(), $attempt + 1, $this->maxRetries, $wait));
                    }
                    sleep($wait);
                } else {
                    // All retries exhausted — spill to disk instead of dropping
                    if ($this->debug) {
                        error_log(sprintf('TeraOps: Send failed after %d retries: %s — spilling %d log(s) to disk', $this->maxRetries, $e->getMessage(), count($logs)));
                    }
                    $this->writeSpillover($logs);
                }
            }
        }
    }

    // ================================================================
    // Disk Spillover
    // ================================================================
    private function writeSpillover(array $logs): void
    {
        if (empty($logs)) {
            return;
        }

        // Check file size cap
        $currentSize = file_exists($this->spilloverFile) ? filesize($this->spilloverFile) : 0;
        if ($currentSize >= self::MAX_DISK_SPILLOVER_SIZE) {
            if ($this->debug) {
                error_log(sprintf('TeraOps: Spillover file at %dMB cap — dropping %d log(s)', self::MAX_DISK_SPILLOVER_SIZE / 1048576, count($logs)));
            }
            return;
        }

        $handle = fopen($this->spilloverFile, 'a');
        if ($handle === false) {
            if ($this->debug) {
                error_log('TeraOps: Could not open spillover file for writing: ' . $this->spilloverFile);
            }
            return;
        }

        foreach ($logs as $log) {
            $line = json_encode($log, JSON_UNESCAPED_UNICODE);
            if ($line !== false) {
                fwrite($handle, $line . "\n");
            }
        }
        fclose($handle);

        if ($this->debug) {
            error_log(sprintf('TeraOps: Spilled %d log(s) to disk: %s', count($logs), $this->spilloverFile));
        }
    }

    private function readSpillover(): array
    {
        // Scan for ALL spillover files (current PID + orphaned from previous processes)
        $dir = dirname($this->spilloverFile);
        $pattern = $dir . '/teraops_spillover_*.jsonl';
        $files = glob($pattern);

        if (empty($files)) {
            return [];
        }

        $logs = [];
        foreach ($files as $file) {
            $handle = fopen($file, 'r');
            if ($handle === false) {
                continue;
            }

            while (($line = fgets($handle)) !== false) {
                $line = trim($line);
                if ($line === '') {
                    continue;
                }
                $decoded = json_decode($line, true);
                if (is_array($decoded)) {
                    $logs[] = $decoded;
                }
            }
            fclose($handle);

            // Delete file after reading
            unlink($file);
        }

        if ($this->debug && !empty($logs)) {
            error_log(sprintf('TeraOps: Recovered %d log(s) from %d spillover file(s)', count($logs), count($files)));
        }

        return $logs;
    }

    // ================================================================
    // Payload Splitting
    // ================================================================
    private function splitByPayloadSize(array $logs): array
    {
        $chunks = [];
        $currentChunk = [];
        $currentSize = 0;

        foreach ($logs as $log) {
            $logSize = strlen(json_encode($log));

            if ($currentSize + $logSize > self::MAX_PAYLOAD_SIZE && !empty($currentChunk)) {
                $chunks[] = $currentChunk;
                $currentChunk = [];
                $currentSize = 0;
            }

            $currentChunk[] = $log;
            $currentSize += $logSize;
        }

        if (!empty($currentChunk)) {
            $chunks[] = $currentChunk;
        }

        return $chunks;
    }

    // ================================================================
    // Shutdown & Force Flush
    // ================================================================
    public function shutdown(?CancellationInterface $cancellation = null): bool
    {
        if ($this->shuttingDown) {
            return true;
        }
        $this->shuttingDown = true;

        if ($this->debug && !empty($this->buffer)) {
            error_log(sprintf('TeraOps: Shutdown — flushing %d remaining log(s)', count($this->buffer)));
        }

        $this->flush();

        if ($this->debug) {
            error_log('TeraOps: SDK shutdown complete');
        }

        return true;
    }

    public function forceFlush(?CancellationInterface $cancellation = null): bool
    {
        $this->flush();
        return true;
    }
}
