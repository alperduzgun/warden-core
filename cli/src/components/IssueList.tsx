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

export function IssueList({issues, maxDisplay = 5}: IssueListProps) {
  if (issues.length === 0) {
    return (
      <Box marginTop={1}>
        <Text color="green">✓ No issues found!</Text>
      </Box>
    );
  }

  // Group issues by severity for summary view
  const groupedBySeverity = issues.reduce((acc, issue) => {
    if (!acc[issue.severity]) {
      acc[issue.severity] = [];
    }
    acc[issue.severity].push(issue);
    return acc;
  }, {} as Record<Severity, Issue[]>);

  const displayIssues = issues.slice(0, maxDisplay);
  const remaining = issues.length - maxDisplay;

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box marginBottom={1}>
        <Text bold underline>Issues Found: {issues.length}</Text>
      </Box>

      {/* Summary by severity */}
      <Box flexDirection="column" marginBottom={1}>
        {(['critical', 'high', 'medium', 'low'] as Severity[]).map(severity => {
          const severityIssues = groupedBySeverity[severity] || [];
          if (severityIssues.length === 0) return null;

          // Get unique issue types for this severity
          const uniqueTypes = [...new Set(severityIssues.map(i => i.rule || i.frame))];
          const typeString = uniqueTypes.slice(0, 3).join(', ');
          const moreTypes = uniqueTypes.length > 3 ? ` +${uniqueTypes.length - 3} more` : '';

          return (
            <Box key={severity}>
              <Text>{SEVERITY_ICONS[severity]} </Text>
              <Text color={SEVERITY_COLORS[severity]} bold>
                {severity.toUpperCase()}
              </Text>
              <Text> [{severityIssues.length}]: </Text>
              <Text dimColor>{typeString}{moreTypes}</Text>
            </Box>
          );
        })}
      </Box>

      {/* Show first few issues in compact format */}
      {displayIssues.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text dimColor>First {Math.min(maxDisplay, issues.length)} issues:</Text>
          {displayIssues.map((issue, index) => {
            // Truncate file path to show only filename
            const fileName = issue.filePath?.split('/').pop() || 'unknown';
            // Truncate message if too long
            const shortMessage = issue.message.length > 60
              ? issue.message.substring(0, 57) + '...'
              : issue.message;

            return (
              <Box key={issue.id || index} marginLeft={2}>
                <Text>{SEVERITY_ICONS[issue.severity]} </Text>
                <Text dimColor>{fileName}:{issue.line} - </Text>
                <Text>{shortMessage}</Text>
              </Box>
            );
          })}
        </Box>
      )}

      {remaining > 0 && (
        <Box marginTop={1}>
          <Text dimColor italic>... and {remaining} more issues</Text>
        </Box>
      )}
    </Box>
  );
}
