/**
 * Scan command
 * Scans a directory or file for validation issues
 */

import React from 'react';
import {Box, Text} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {IssueList} from '../components/IssueList.js';
import {useIPC} from '../hooks/useIPC.js';
import type {ScanResult} from '../lib/types.js';

interface ScanProps {
  path: string;
  frames?: string[] | undefined;
}

export function Scan({path, frames}: ScanProps) {
  const {data, loading, error} = useIPC<ScanResult>({
    command: 'scan',
    params: {path, frames},
  });

  if (loading) {
    return <Spinner message={`Scanning ${path}...`} />;
  }

  if (error) {
    return (
      <Box flexDirection="column">
        <Text color="red">✗ Error:</Text>
        <Text color="red">{error.message}</Text>
      </Box>
    );
  }

  if (!data) {
    return <Text color="yellow">No data received</Text>;
  }

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold color="green">✓ Scan Complete</Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text>Files scanned: <Text bold>{data.filesScanned}</Text></Text>
        <Text>Duration: <Text bold>{(data.duration / 1000).toFixed(2)}s</Text></Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text bold>Summary:</Text>
        <Text>  🔴 Critical: <Text bold color="red">{data.summary.critical}</Text></Text>
        <Text>  🟠 High: <Text bold color="redBright">{data.summary.high}</Text></Text>
        <Text>  🟡 Medium: <Text bold color="yellow">{data.summary.medium}</Text></Text>
        <Text>  ⚪ Low: <Text bold color="gray">{data.summary.low}</Text></Text>
      </Box>

      <IssueList issues={data.issues} />
    </Box>
  );
}
