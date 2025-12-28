/**
 * Scan command
 * Scans a directory or file for validation issues
 */

import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {IssueList} from '../components/IssueList.js';
import {useIPC} from '../hooks/useIPC.js';
import {backendManager} from '../lib/backend-manager.js';
import {resolvePath, validatePath} from '../lib/path-utils.js';
import {LoadingIndicator, ConnectionStatus} from '../components/LoadingIndicator.js';
import {ErrorDisplay} from '../utils/errors.js';
import type {ScanResult} from '../lib/types.js';

interface ScanProps {
  path: string;
  frames?: string[] | undefined;
}

export function Scan({path, frames}: ScanProps) {
  const [backendReady, setBackendReady] = useState(false);
  const [isConnecting, setIsConnecting] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [resolvedPath, setResolvedPath] = useState<string>('');
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    // Validate and resolve path first
    const pathValidation = validatePath(path);
    if (!pathValidation.valid) {
      setStartupError(pathValidation.error || 'Invalid path');
      setIsConnecting(false);
      return;
    }

    const resolved = resolvePath(path);
    setResolvedPath(resolved);

    // Then ensure backend is running with retry logic
    const startBackend = async () => {
      for (let i = 0; i <= 3; i++) {
        try {
          setRetryCount(i);
          await backendManager.ensureRunning();
          setBackendReady(true);
          setIsConnecting(false);
          break;
        } catch (error) {
          if (i === 3) {
            setStartupError(error instanceof Error ? error.message : 'Backend startup failed');
            setIsConnecting(false);
          } else {
            // Wait before retry
            await new Promise(resolve => setTimeout(resolve, 2000));
          }
        }
      }
    };

    startBackend();
  }, [path]);

  const {data, loading, error} = useIPC<ScanResult>({
    command: 'scan',
    params: {path: resolvedPath, frames},
    autoExecute: backendReady && !!resolvedPath,
  });

  // Show startup errors with helpful suggestions
  if (startupError) {
    return <ErrorDisplay error={startupError} />;
  }

  // Show connection status while connecting
  if (isConnecting) {
    return (
      <ConnectionStatus
        isConnecting={true}
        isConnected={false}
        retryCount={retryCount}
        maxRetries={3}
      />
    );
  }

  // Show loading with better feedback
  if (!backendReady || loading) {
    return (
      <LoadingIndicator
        message={!backendReady ? "Starting Warden backend" : `Scanning ${path}`}
        subMessage={!backendReady ? "Initializing Python services..." : `Analyzing files with ${frames?.join(', ') || 'all'} frames`}
        showTimer={true}
        timeoutWarning={15}
      />
    );
  }

  // Show scan errors with helpful context
  if (error) {
    return <ErrorDisplay error={error} />;
  }

  if (!data) {
    return <Text color="yellow">No data received</Text>;
  }

  // Handle different response formats gracefully
  const filesScanned = data.filesScanned || (data as any).files_scanned || 0;
  const duration = data.duration || 0;
  const issues = data.issues || [];

  // Handle summary data - it might be nested or missing
  const summary = data.summary || {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0
  };

  // If summary doesn't exist but issues do, calculate from issues
  if (!data.summary && issues.length > 0) {
    summary.critical = issues.filter((i: any) => i.severity === 'critical').length;
    summary.high = issues.filter((i: any) => i.severity === 'high').length;
    summary.medium = issues.filter((i: any) => i.severity === 'medium').length;
    summary.low = issues.filter((i: any) => i.severity === 'low').length;
  }

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold color="green">✓ Scan Complete</Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text>Files scanned: <Text bold>{filesScanned}</Text></Text>
        <Text>Duration: <Text bold>{(duration / 1000).toFixed(2)}s</Text></Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text bold>Summary:</Text>
        <Text>  🔴 Critical: <Text bold color="red">{summary.critical || 0}</Text></Text>
        <Text>  🟠 High: <Text bold color="redBright">{summary.high || 0}</Text></Text>
        <Text>  🟡 Medium: <Text bold color="yellow">{summary.medium || 0}</Text></Text>
        <Text>  ⚪ Low: <Text bold color="gray">{summary.low || 0}</Text></Text>
      </Box>

      {issues.length > 0 ? (
        <IssueList issues={issues} />
      ) : (
        <Box marginTop={1}>
          <Text color="green">✨ No issues found!</Text>
        </Box>
      )}
    </Box>
  );
}
