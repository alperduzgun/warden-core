/**
 * Analyze command with streaming pipeline progress
 * Runs full analysis pipeline on a single file with real-time updates
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import {ipcClient} from '../lib/ipc-client.js';
import {backendManager} from '../lib/backend-manager.js';
import {PipelineProgressDisplay, type FrameProgress} from '../components/PipelineProgressDisplay.js';
import {logger} from '../utils/logger.js';
import {resolvePath, validatePath} from '../lib/path-utils.js';
import {LoadingIndicator} from '../components/LoadingIndicator.js';
import {ErrorDisplay} from '../utils/errors.js';

interface AnalyzeProps {
  filePath: string;
}

interface StreamEvent {
  type: 'progress' | 'result' | 'error';
  event?: string;
  data?: any;
  message?: string;
}

interface PipelineResult {
  pipeline_id: string;
  status: string;
  duration: number;
  total_findings: number;
  critical_findings: number;
  high_findings: number;
  medium_findings: number;
  low_findings: number;
  frame_results: Array<{
    frame_id: string;
    frame_name: string;
    status: string;
    duration: number;
    issues_found: number;
    findings: Array<{
      severity: string;
      message: string;
      line?: number;
      code?: string;
      file?: string;
    }>;
  }>;
}

export function Analyze({filePath}: AnalyzeProps) {
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [frames, setFrames] = useState<FrameProgress[]>([]);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [totalDuration, setTotalDuration] = useState<string>('');
  const startTime = React.useRef(Date.now());
  const [shouldExit, setShouldExit] = useState(false);

  useEffect(() => {
    runAnalysis();
  }, [filePath]);

  // Exit after showing results for a longer time to let users read
  useEffect(() => {
    if (result || error) {
      const timer = setTimeout(() => {
        setShouldExit(true);
        // Give more time for errors to be read
        const delay = error ? 5000 : 3000;
        setTimeout(() => process.exit(result ? 0 : 1), delay);
      }, 100);
      return () => clearTimeout(timer);
    }
    return undefined; // Explicitly return undefined when there's no cleanup needed
  }, [result, error]);

  const runAnalysis = async () => {
    try {
      // Validate and resolve the file path
      const pathValidation = validatePath(filePath);
      if (!pathValidation.valid) {
        setError(pathValidation.error || 'Invalid file path');
        setLoading(false);
        return;
      }

      const resolvedPath = resolvePath(filePath);

      // Ensure backend is running (auto-start if needed)
      await backendManager.ensureRunning();

      // Connect to backend if not connected
      if (!ipcClient.isConnected()) {
        await ipcClient.connect();
      }
      setConnecting(false);

      // Initialize frames from config
      const configResult = await ipcClient.send<any>('get_config', {});
      if (configResult.success && configResult.data?.frames) {
        const initialFrames: FrameProgress[] = configResult.data.frames.map((frame: any) => ({
          id: frame.id,
          name: frame.name,
          status: 'pending' as const,
        }));
        setFrames(initialFrames);
      }

      // Start streaming pipeline execution with resolved path
      await ipcClient.sendStream<StreamEvent>(
        'execute_pipeline_stream',
        {file_path: resolvedPath},
        (event: StreamEvent) => {
          logger.debug('stream_event_received', {
            type: event.type,
            event: event.event,
          });

          if (event.type === 'progress') {
            handleProgressEvent(event);
          } else if (event.type === 'result') {
            handleResultEvent(event.data);
          } else if (event.type === 'error') {
            setError(event.message || 'Pipeline execution failed');
            setLoading(false);
          }
        }
      );
    } catch (err) {
      logger.error('analyze_failed', {error: String(err)});
      setError(err instanceof Error ? err.message : 'Unknown error');
      setLoading(false);
    }
  };

  const handleProgressEvent = (event: StreamEvent) => {
    const {event: eventName, data} = event;

    switch (eventName) {
      case 'pipeline_started':
        logger.info('pipeline_started', data);
        startTime.current = Date.now();
        break;

      case 'frame_started':
        logger.info('frame_started', data);
        setFrames(prev =>
          prev.map(frame =>
            frame.id === data.frame_id
              ? {...frame, status: 'running' as const}
              : frame
          )
        );
        break;

      case 'frame_completed':
        logger.info('frame_completed', data);
        setFrames(prev =>
          prev.map(frame =>
            frame.id === data.frame_id
              ? {
                  ...frame,
                  status: data.status === 'passed' ? ('completed' as const)
                        : data.status === 'failed' ? ('failed' as const)
                        : ('warning' as const),
                  ...(data.duration && { duration: `${data.duration.toFixed(1)}s` }),
                  ...(data.issues_found && { issues: data.issues_found }),
                }
              : frame
          )
        );
        break;

      case 'pipeline_completed':
        logger.info('pipeline_completed', data);
        const elapsed = ((Date.now() - startTime.current) / 1000).toFixed(1);
        setTotalDuration(`${elapsed}s`);
        break;
    }
  };

  const handleResultEvent = (data: PipelineResult) => {
    logger.info('pipeline_result', {
      total_findings: data.total_findings,
      status: data.status,
    });
    setResult(data);
    setLoading(false);
  };

  // Show connection status with better feedback
  if (connecting) {
    return (
      <LoadingIndicator
        message="Connecting to Warden backend"
        subMessage="Establishing connection to analysis service..."
        showTimer={true}
        timeoutWarning={10}
      />
    );
  }

  // Show error with helpful context
  if (error) {
    return <ErrorDisplay error={error} showDetails={true} />;
  }

  // Show progress while running
  if (loading && frames.length > 0) {
    return (
      <Box flexDirection="column">
        <Box marginBottom={1}>
          <Text bold>Analyzing: <Text color="cyan">{filePath}</Text></Text>
        </Box>
        <PipelineProgressDisplay
          frames={frames}
          totalDuration={totalDuration}
        />
      </Box>
    );
  }

  // Show results
  if (result) {
    const hasFindings = result.total_findings > 0;
    const severityColors = {
      critical: 'red',
      high: 'magenta',
      medium: 'yellow',
      low: 'cyan',
    };

    return (
      <Box flexDirection="column">
        {/* Header */}
        <Box marginBottom={1}>
          <Text bold color={result.status === 'success' ? 'green' : 'red'}>
            {result.status === 'success' ? '✓' : '✗'} Analysis Complete
          </Text>
          <Text dimColor> - {totalDuration || `${result.duration.toFixed(1)}s`}</Text>
        </Box>

        {/* File info */}
        <Box marginBottom={1}>
          <Text>File: <Text bold>{filePath}</Text></Text>
        </Box>

        {/* Show completed frame progress */}
        <PipelineProgressDisplay
          frames={frames}
          totalDuration={totalDuration}
        />

        {/* Findings Summary */}
        {hasFindings && (
          <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor="yellow" padding={1}>
            <Box marginBottom={1}>
              <Text bold>📊 Findings Summary ({result.total_findings} total)</Text>
            </Box>

            <Box flexDirection="column">
              {result.critical_findings > 0 && (
                <Text color="red">
                  🔴 Critical: {result.critical_findings}
                </Text>
              )}
              {result.high_findings > 0 && (
                <Text color="magenta">
                  🟣 High: {result.high_findings}
                </Text>
              )}
              {result.medium_findings > 0 && (
                <Text color="yellow">
                  🟡 Medium: {result.medium_findings}
                </Text>
              )}
              {result.low_findings > 0 && (
                <Text color="cyan">
                  🔵 Low: {result.low_findings}
                </Text>
              )}
            </Box>

            {/* Detailed Findings */}
            {result.frame_results?.map((frameResult) => {
              if (frameResult.findings?.length === 0) return null;

              return (
                <Box key={frameResult.frame_id} flexDirection="column" marginTop={1}>
                  <Text bold dimColor>
                    {frameResult.frame_name} ({frameResult.findings.length} issues):
                  </Text>
                  {frameResult.findings.slice(0, 5).map((finding, idx) => (
                    <Box key={idx} marginLeft={2} marginTop={0}>
                      <Text color={severityColors[finding.severity as keyof typeof severityColors] || 'white'}>
                        • {finding.message}
                        {finding.line && <Text dimColor> (line {finding.line})</Text>}
                      </Text>
                      {finding.code && (
                        <Box marginLeft={2}>
                          <Text dimColor>{finding.code}</Text>
                        </Box>
                      )}
                    </Box>
                  ))}
                  {frameResult.findings.length > 5 && (
                    <Box marginLeft={2}>
                      <Text dimColor>
                        ... and {frameResult.findings.length - 5} more
                      </Text>
                    </Box>
                  )}
                </Box>
              );
            })}
          </Box>
        )}

        {/* No findings */}
        {!hasFindings && (
          <Box marginTop={1} borderStyle="single" borderColor="green" padding={1}>
            <Text color="green">✨ No issues found! Your code looks great.</Text>
          </Box>
        )}
      </Box>
    );
  }

  // Loading state (initial) with better feedback
  return (
    <LoadingIndicator
      message="Initializing analysis pipeline"
      subMessage="Preparing validation frames..."
      showTimer={false}
    />
  );
}