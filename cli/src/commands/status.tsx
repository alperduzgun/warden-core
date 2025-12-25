/**
 * Status command
 * Shows Warden backend status and configuration
 */

import React from 'react';
import {Box, Text} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {useIPC} from '../hooks/useIPC.js';
import type {StatusResponse} from '../lib/types.js';

export function Status() {
  const {data, loading, error} = useIPC<StatusResponse>({
    command: 'ping',
  });

  if (loading) {
    return <Spinner message="Checking status..." />;
  }

  if (error) {
    return (
      <Box flexDirection="column">
        <Text color="red">✗ Backend not connected</Text>
        <Text dimColor>Make sure Warden backend is running:</Text>
        <Text dimColor>  python3 start_ipc_server.py</Text>
      </Box>
    );
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
