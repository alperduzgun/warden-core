/**
 * Pipeline Display Component
 * Shows real-time 6-phase pipeline execution with animations
 * Inspired by warden-panel dashboard sidebar
 */

import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';

// Pipeline phase definitions matching backend
export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface PipelinePhase {
  id: string;
  name: string;
  status: PhaseStatus;
  duration?: string | undefined;
  icon?: string | undefined;
  subSteps?: SubStep[] | undefined;
}

export interface SubStep {
  id: string;
  name: string;
  status: PhaseStatus;
  duration?: string | undefined;
}

export interface PipelineDisplayProps {
  phases: PipelinePhase[];
  currentPhase?: string | undefined;
  currentSubStep?: string | undefined;
  totalDuration?: string | undefined;
  showDetails?: boolean | undefined;
  compact?: boolean | undefined;
  forceState?: 'completed' | 'failed' | undefined;
}

// Phase configuration with icons
const PHASE_CONFIG = {
  'pre-analysis': { icon: '🔍', displayName: 'Pre-Analysis' },
  'analysis': { icon: '📊', displayName: 'Analysis' },
  'classification': { icon: '🏷️', displayName: 'Classification' },
  'validation': { icon: '✓', displayName: 'Validation' },
  'fortification': { icon: '🛡️', displayName: 'Fortification' },
  'cleaning': { icon: '✨', displayName: 'Cleaning' },
};

// Validation substeps
const VALIDATION_SUBSTEPS = [
  'security',
  'chaos',
  'fuzz',
  'property',
  'stress',
  'architectural'
];

const getStatusIcon = (status: PhaseStatus): string => {
  switch (status) {
    case 'completed':
      return '✓';
    case 'failed':
      return '✗';
    case 'skipped':
      return '⊘';
    case 'running':
      return '';  // Will use spinner
    case 'pending':
    default:
      return '○';
  }
};

const getStatusColor = (status: PhaseStatus): string => {
  switch (status) {
    case 'completed':
      return 'green';
    case 'failed':
      return 'red';
    case 'skipped':
      return 'gray';
    case 'running':
      return 'cyan';
    case 'pending':
    default:
      return 'gray';
  }
};

const ProgressItem = ({
  name,
  status,
  duration,
  icon,
  isSubStep = false,
  children
}: {
  name: string;
  status: PhaseStatus;
  duration?: string | undefined;
  icon?: string | undefined;
  isSubStep?: boolean;
  children?: React.ReactNode;
}) => {
  const statusColor = getStatusColor(status);
  const statusIcon = getStatusIcon(status);

  // Visual bar for running/completed states (to match Frame Statistics look)
  // For phases without numeric progress, we show a full or empty bar based on status
  const barWidth = 20;
  const isComplete = status === 'completed';
  const isRunning = status === 'running';
  const filledCount = isComplete ? barWidth : (isRunning ? Math.floor(Date.now() / 500) % barWidth : 0);

  // Simplified bar logic:
  // Completed: Full Green
  // Running: Animated Cyan (handled by simple static for now or just text)
  // Pending: Empty

  // Actually, let's just use the textual status aligned like the Frame Stats "Coverage" line for consistency
  // Frame Stats: "Coverage: [|||||] 50%"
  // Here:        "Status:   [|||||] RUNNING"

  let barDisplay = '░'.repeat(barWidth);
  if (isComplete) {
    barDisplay = '█'.repeat(barWidth);
  } else if (status === 'failed') {
    barDisplay = '█'.repeat(barWidth); // Full red bar? or partial? match status
  } else if (isRunning) {
    // Indeterminate animation handled by parent or just show partial
    barDisplay = '▒'.repeat(barWidth);
  }

  return (
    <Box flexDirection="column" marginLeft={isSubStep ? 1 : 0}>
      <Box>
        <Box width={2}>
          <Text color={statusColor}>{statusIcon} </Text>
        </Box>
        <Box width={30}>
          <Text bold>{icon} {name}</Text>
        </Box>
        {duration && <Text dimColor> [{duration}]</Text>}
      </Box>
      {(status === 'running' || status === 'completed' || status === 'failed') && (
        <Box marginLeft={2}>
          <Text dimColor>{isSubStep ? 'Progress: ' : 'Status:   '}</Text>
          <Text color={statusColor}>{barDisplay} {status.toUpperCase()}</Text>
        </Box>
      )}
      {children}
    </Box>
  );
};

export function PipelineDisplay({
  phases,
  currentPhase,
  currentSubStep,
  totalDuration,
  showDetails = true,
  compact = false,
  forceState
}: PipelineDisplayProps) {
  const [animationDots, setAnimationDots] = useState('');

  // Animate dots for running state
  useEffect(() => {
    const interval = setInterval(() => {
      setAnimationDots(prev => prev.length >= 3 ? '' : prev + '.');
    }, 500);
    return () => clearInterval(interval);
  }, []);

  // Calculate progress - only count actually running/completed phases, not pending
  const executedPhases = phases.filter(p => p.status !== 'pending');
  const completedCount = phases.filter(p => p.status === 'completed').length;
  const totalPhases = executedPhases.length > 0 ? executedPhases.length : phases.length;
  const progressPercentage = totalPhases > 0 ? Math.round((completedCount / totalPhases) * 100) : 0;

  // Compact mode: show just a summary line
  if (compact) {
    const failedCount = phases.filter(p => p.status === 'failed').length;
    // Trust forceState if provided, otherwise check phases
    const isComplete = forceState ? true : phases.every(p => p.status !== 'pending' && p.status !== 'running');
    const displayFailed = forceState === 'failed' || failedCount > 0;

    return (
      <Box>
        <Text>
          Pipeline {isComplete ? (
            displayFailed ? (
              <Text color="red" bold>FAILED</Text>
            ) : (
              <Text color="green" bold>COMPLETED</Text>
            )
          ) : (
            <Text color="cyan">RUNNING ({progressPercentage}%)</Text>
          )}
          {totalDuration && <Text dimColor> in {totalDuration}</Text>}
          <Text dimColor> | {completedCount}/{totalPhases} phases</Text>
        </Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" padding={0} paddingX={1} marginBottom={0}>
      {/* Header */}
      <Box marginBottom={0} flexDirection="column">
        <Box>
          <Text bold color="cyan">
            🚀 Pipeline Execution
          </Text>
          <Text color="gray"> ({progressPercentage}%)</Text>
        </Box>
        {totalDuration && (
          <Text dimColor>Duration: {totalDuration}</Text>
        )}
      </Box>

      {/* Global Progress Bar */}
      <Box marginBottom={1}>
        <Text>
          {'['}
          {Array.from({ length: 40 }).map((_, i) => {
            const filled = totalPhases > 0 ? i < Math.floor((completedCount / totalPhases) * 40) : false;
            return filled ? '█' : '░';
          }).join('')}
          {']'}
        </Text>
      </Box>

      {/* Pipeline Phases */}
      <Box flexDirection="column" marginTop={1}>
        {phases.map((phase) => {
          // If phase is pending, don't show it unless it's the very next one? 
          // User said "tüm fazlar çalışırken" (while all phases are running).
          // Showing all provides context.

          const config = PHASE_CONFIG[phase.id as keyof typeof PHASE_CONFIG];

          // Special handling for Validation to show sub-steps
          const showSubSteps = showDetails && phase.id === 'validation' && phase.subSteps && phase.subSteps.length > 0;

          return (
            <ProgressItem
              key={phase.id}
              name={config?.displayName || phase.name}
              status={phase.status}
              duration={phase.duration}
              icon={config?.icon}
            >
              {showSubSteps && (
                <Box flexDirection="column" marginTop={1}>
                  {phase.subSteps!.map(subStep => (
                    <ProgressItem
                      key={subStep.id}
                      name={subStep.name}
                      status={subStep.status}
                      duration={subStep.duration}
                      icon="▪"
                      isSubStep={true}
                    />
                  ))}
                </Box>
              )}
            </ProgressItem>
          );
        })}
      </Box>
    </Box>
  );
}

// Helper function to create initial phase structure
export function createInitialPhases(): PipelinePhase[] {
  return [
    { id: 'pre-analysis', name: 'Pre-Analysis', status: 'pending' },
    { id: 'analysis', name: 'Analysis', status: 'pending' },
    { id: 'classification', name: 'Classification', status: 'pending' },
    {
      id: 'validation',
      name: 'Validation',
      status: 'pending',
      subSteps: VALIDATION_SUBSTEPS.map(id => ({
        id,
        name: id.charAt(0).toUpperCase() + id.slice(1),
        status: 'pending' as PhaseStatus
      }))
    },
    { id: 'fortification', name: 'Fortification', status: 'pending' },
    { id: 'cleaning', name: 'Cleaning', status: 'pending' }
  ];
}

// Helper function to update phase status
export function updatePhaseStatus(
  phases: PipelinePhase[],
  phaseId: string,
  status: PhaseStatus,
  duration?: string
): PipelinePhase[] {
  return phases.map(phase => {
    if (phase.id === phaseId) {
      return { ...phase, status, duration };
    }
    return phase;
  });
}

// Helper function to update substep status
export function updateSubStepStatus(
  phases: PipelinePhase[],
  phaseId: string,
  subStepId: string,
  status: PhaseStatus,
  duration?: string
): PipelinePhase[] {
  return phases.map(phase => {
    if (phase.id === phaseId && phase.subSteps) {
      return {
        ...phase,
        subSteps: phase.subSteps.map(subStep => {
          if (subStep.id === subStepId) {
            return { ...subStep, status, duration };
          }
          return subStep;
        })
      };
    }
    return phase;
  });
}