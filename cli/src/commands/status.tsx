/**
 * Status command
 * Shows Warden backend status and configuration
 */

import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {useIPC} from '../hooks/useIPC.js';
import {backendManager} from '../lib/backend-manager.js';
import {LoadingIndicator} from '../components/LoadingIndicator.js';
import {ErrorDisplay} from '../utils/errors.js';
import type {StatusResponse} from '../lib/types.js';

export function Status() {
  const [backendReady, setBackendReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);

  useEffect(() => {
    // Ensure backend is running before checking status
    backendManager.ensureRunning()
      .then(() => setBackendReady(true))
      .catch((error) => setStartupError(error.message));
  }, []);

  const {data, loading, error} = useIPC<StatusResponse>({
    command: 'ping',
    // Only send command when backend is ready
    autoExecute: backendReady,
  });

  if (startupError) {
    return <ErrorDisplay error={startupError} showDetails={true} />;
  }

  if (!backendReady || loading) {
    return (
      <LoadingIndicator
        message="Checking Warden backend status"
        subMessage="Connecting to backend service..."
        showTimer={true}
        timeoutWarning={5}
      />
    );
  }

  if (error) {
    return <ErrorDisplay error={error} showDetails={true} />;
  }

  if (!data) {
    return <Text color="yellow">No data received</Text>;
  }

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold color="green">✓ Warden Backend Connected</Text>
      </Box>

      <Box flexDirection="column">
        <Text>Status: <Text bold color="green">{(data as any).status || 'ok'}</Text></Text>
        <Text>Message: <Text bold>{(data as any).message || data.version}</Text></Text>
        {(data as any).timestamp && (
          <Text>Timestamp: <Text dimColor>{(data as any).timestamp}</Text></Text>
        )}
      </Box>
    </Box>
  );
}
