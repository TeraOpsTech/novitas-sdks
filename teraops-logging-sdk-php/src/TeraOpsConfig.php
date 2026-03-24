<?php

declare(strict_types=1);

namespace TeraOps\Logging;

use OpenTelemetry\SDK\Logs\LoggerProviderInterface;
use OpenTelemetry\SDK\Logs\Processor\SimpleLogRecordProcessor;

/**
 * Attach TeraOps exporter to your existing OTEL LoggerProvider.
 *
 * This is all the customer needs to do:
 *
 *     use TeraOps\Logging\TeraOpsConfig;
 *
 *     TeraOpsConfig::attach(
 *         $loggerProvider,
 *         apiKey: $_ENV['TERAOPS_API_KEY'],
 *         apiUrl: $_ENV['TERAOPS_API_URL'],
 *     );
 *
 * That's it. One function call. Everything else is automatic:
 *     - Logs are buffered and sent in batches
 *     - Secrets are redacted before sending
 *     - System info (hostname, pid, etc.) is auto-enriched
 *     - Oversized messages are truncated
 *     - Format issues are tagged (_formatted, _format_issues)
 */
class TeraOpsConfig
{
    /**
     * Attach TeraOps exporter to your existing OTEL LoggerProvider.
     *
     * Your existing exporters (Datadog, New Relic, Console, etc.) keep working.
     * TeraOps is added alongside — both get every log.
     *
     * @param LoggerProviderInterface $loggerProvider Your existing OTEL LoggerProvider
     * @param string $apiKey TeraOps API key (provided by TeraOps on signup)
     * @param string $apiUrl TeraOps API base URL
     * @param string $logType Log type identifier
     * @param bool $liveLogs If true, sends historical_data=true
     * @param bool $debug If true, shows SDK debug logs via error_log
     * @param bool $validateApiKey If true, validates API key on startup
     * @return TeraOpsLogExporter The exporter instance (most customers ignore this)
     */
    public static function attach(
        LoggerProviderInterface $loggerProvider,
        string $apiKey,
        string $apiUrl,
        string $logType = 'otel',
        bool $liveLogs = false,
        bool $debug = false,
        bool $validateApiKey = true,
    ): TeraOpsLogExporter {
        $exporter = new TeraOpsLogExporter(
            apiUrl: $apiUrl,
            apiKey: $apiKey,
            logType: $logType,
            liveLogs: $liveLogs,
            debug: $debug,
            validateApiKey: $validateApiKey,
        );

        $processor = new SimpleLogRecordProcessor($exporter);
        $loggerProvider->addLogRecordProcessor($processor);

        return $exporter;
    }
}
