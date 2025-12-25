/**
 * Issue list component
 * Displays validation issues in a formatted list
 */

import React from 'react';
import {Box, Text} from 'ink';
import type {Issue, Severity} from '../lib/types.js';

interface IssueListProps {
  issues: Issue[];
  maxDisplay?: number;
}

const SEVERITY_COLORS: Record<Severity, string> = {
  critical: 'red',
  high: 'redBright',
  medium: 'yellow',
  low: 'gray',
};

const SEVERITY_ICONS: Record<Severity, string> = {
  critical: '🔴',
  high: '🟠',
  medium: '🟡',
  low: '⚪',
};

export function IssueList({issues, maxDisplay = 10}: IssueListProps) {
  if (issues.length === 0) {
    return (
      <Box marginTop={1}>
        <Text color="green">✓ No issues found!</Text>
      </Box>
    );
  }

  const displayIssues = issues.slice(0, maxDisplay);
  const remaining = issues.length - maxDisplay;

  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold>Issues Found: {issues.length}</Text>
      <Box flexDirection="column" marginTop={1}>
        {displayIssues.map((issue, index) => (
          <Box key={issue.id || index} marginBottom={1} flexDirection="column">
            <Box>
              <Text>{SEVERITY_ICONS[issue.severity]} </Text>
              <Text color={SEVERITY_COLORS[issue.severity]} bold>
                {issue.severity.toUpperCase()}
              </Text>
              <Text dimColor> [{issue.frame}] {issue.rule}</Text>
            </Box>
            <Box marginLeft={2}>
              <Text dimColor>{issue.filePath}:{issue.line}:{issue.column}</Text>
            </Box>
            <Box marginLeft={2}>
              <Text>{issue.message}</Text>
            </Box>
          </Box>
        ))}
      </Box>
      {remaining > 0 && (
        <Text dimColor>... and {remaining} more issues</Text>
      )}
    </Box>
  );
}
