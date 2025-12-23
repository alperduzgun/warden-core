/**
 * IssueSummary Component
 *
 * Displays a summary of issues found during validation.
 * Shows severity counts and individual issue listings.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Finding } from '../bridge/wardenClient.js';

export interface IssueSummaryProps {
  /**
   * List of findings/issues
   */
  issues: Finding[];

  /**
   * Maximum number of issues to display
   * @default 10
   */
  maxDisplay?: number;

  /**
   * Show severity badge colors
   * @default true
   */
  showColors?: boolean;

  /**
   * Compact mode (single line)
   * @default false
   */
  compact?: boolean;
}

/**
 * Display summary of validation issues
 *
 * @example
 * ```tsx
 * const issues = [
 *   { severity: 'critical', message: 'SQL Injection vulnerability', line: 42 },
 *   { severity: 'high', message: 'Hardcoded password', line: 15 }
 * ];
 * <IssueSummary issues={issues} />
 * ```
 */
export const IssueSummary: React.FC<IssueSummaryProps> = ({
  issues,
  maxDisplay = 10,
  showColors = true,
  compact = false,
}) => {
  // Calculate severity counts
  const severityCounts = {
    critical: issues.filter((i) => i.severity === 'critical').length,
    high: issues.filter((i) => i.severity === 'high').length,
    medium: issues.filter((i) => i.severity === 'medium').length,
    low: issues.filter((i) => i.severity === 'low').length,
  };

  const totalIssues = issues.length;

  if (totalIssues === 0) {
    return (
      <Box>
        <Text color="green">✓ No issues found</Text>
      </Box>
    );
  }

  if (compact) {
    return (
      <Box>
        <Text bold>Issues: </Text>
        <Text color="red">{severityCounts.critical} critical</Text>
        <Text color="gray"> · </Text>
        <Text color="yellow">{severityCounts.high} high</Text>
        <Text color="gray"> · </Text>
        <Text color="cyan">{severityCounts.medium} medium</Text>
        <Text color="gray"> · </Text>
        <Text color="gray">{severityCounts.low} low</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box>
        <Text bold>Issue Summary ({totalIssues} total):</Text>
      </Box>

      {/* Severity badges */}
      <Box marginLeft={2}>
        <SeverityBadge
          severity="critical"
          count={severityCounts.critical}
          showColors={showColors}
        />
        <SeverityBadge
          severity="high"
          count={severityCounts.high}
          showColors={showColors}
        />
        <SeverityBadge
          severity="medium"
          count={severityCounts.medium}
          showColors={showColors}
        />
        <SeverityBadge
          severity="low"
          count={severityCounts.low}
          showColors={showColors}
        />
      </Box>

      {/* Issue list */}
      <Box marginTop={1} flexDirection="column">
        {issues.slice(0, maxDisplay).map((issue, idx) => (
          <IssueItem key={idx} issue={issue} index={idx} showColors={showColors} />
        ))}
      </Box>

      {/* "More issues" indicator */}
      {totalIssues > maxDisplay && (
        <Box marginTop={1} marginLeft={2}>
          <Text color="gray">
            ... and {totalIssues - maxDisplay} more issue
            {totalIssues - maxDisplay !== 1 ? 's' : ''}
          </Text>
        </Box>
      )}
    </Box>
  );
};

/**
 * Severity badge with count
 */
interface SeverityBadgeProps {
  severity: 'critical' | 'high' | 'medium' | 'low';
  count: number;
  showColors: boolean;
}

const SeverityBadge: React.FC<SeverityBadgeProps> = ({
  severity,
  count,
  showColors,
}) => {
  const colors = {
    critical: 'red',
    high: 'yellow',
    medium: 'cyan',
    low: 'gray',
  };

  const icons = {
    critical: '🔴',
    high: '🟡',
    medium: '🔵',
    low: '⚪',
  };

  if (count === 0) {
    return null;
  }

  return (
    <Box marginRight={2}>
      <Text color={showColors ? colors[severity] : 'white'}>
        {icons[severity]} {severity}: {count}
      </Text>
    </Box>
  );
};

/**
 * Individual issue item
 */
interface IssueItemProps {
  issue: Finding;
  index: number;
  showColors: boolean;
}

const IssueItem: React.FC<IssueItemProps> = ({ issue, index, showColors }) => {
  const colors = {
    critical: 'red',
    high: 'yellow',
    medium: 'cyan',
    low: 'gray',
  };

  const severityColor = showColors
    ? (colors[issue.severity as keyof typeof colors] || 'white')
    : 'white';

  return (
    <Box marginLeft={2}>
      <Text color="gray">{index + 1}. </Text>
      <Text color={severityColor} bold>
        [{issue.severity.toUpperCase()}]
      </Text>
      <Text> {issue.message}</Text>
      {issue.line !== undefined && (
        <Text color="gray"> (line {issue.line})</Text>
      )}
    </Box>
  );
};

/**
 * Compact severity indicator (just icons)
 */
export interface SeverityIndicatorProps {
  severity: 'critical' | 'high' | 'medium' | 'low';
}

export const SeverityIndicator: React.FC<SeverityIndicatorProps> = ({
  severity,
}) => {
  const icons = {
    critical: '🔴',
    high: '🟡',
    medium: '🔵',
    low: '⚪',
  };

  const colors = {
    critical: 'red',
    high: 'yellow',
    medium: 'cyan',
    low: 'gray',
  };

  return (
    <Text color={colors[severity]}>
      {icons[severity]} {severity.toUpperCase()}
    </Text>
  );
};

export default IssueSummary;
