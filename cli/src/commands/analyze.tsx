/**
 * Analyze command
 * Runs full analysis pipeline on a single file
 */

import React from 'react';
import {Box, Text} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {IssueList} from '../components/IssueList.js';
import {useIPC} from '../hooks/useIPC.js';
import type {ValidationResult} from '../lib/types.js';

interface AnalyzeProps {
  filePath: string;
}

export function Analyze({filePath}: AnalyzeProps) {
  const {data, loading, error} = useIPC<ValidationResult>({
    command: 'analyze',
    params: {filePath},
  });

  if (loading) {
    return <Spinner message={`Analyzing ${filePath}...`} />;
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
        <Text bold color={data.success ? 'green' : 'red'}>
          {data.success ? '✓' : '✗'} Analysis Complete
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text>Frame: <Text bold>{data.frame}</Text></Text>
        <Text>File: <Text bold>{filePath}</Text></Text>
      </Box>

      <IssueList issues={data.issues} />
    </Box>
  );
}
