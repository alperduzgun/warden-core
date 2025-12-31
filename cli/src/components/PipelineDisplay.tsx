/**
 * Pipeline Display Component
 * Shows real-time 6-phase pipeline execution with animations
 * Inspired by warden-panel dashboard sidebar
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
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

export function PipelineDisplay({
  phases,
  currentPhase,
  currentSubStep,
  totalDuration,
  showDetails = true,
  compact = false
}: PipelineDisplayProps) {
  const [animationDots, setAnimationDots] = useState('');

  // Animate dots for running state
  useEffect(() => {
    const interval = setInterval(() => {
      setAnimationDots(prev => prev.length >= 3 ? '' : prev + '.');
    }, 500);
    return () => clearInterval(interval);
  }, []);

  // Calculate progress
  const completedCount = phases.filter(p => p.status === 'completed').length;
  const totalPhases = phases.length;
  const progressPercentage = Math.round((completedCount / totalPhases) * 100);

  // Compact mode: show just a summary line
  if (compact) {
    const failedCount = phases.filter(p => p.status === 'failed').length;
    const isComplete = phases.every(p => p.status !== 'pending' && p.status !== 'running');

    return (
      <Box>
        <Text>
          Pipeline {isComplete ? (
            failedCount > 0 ? (
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
    <Box flexDirection="column">
      {/* Header */}
      <Box marginBottom={1} flexDirection="column">
        <Box>
          <Text bold color="cyan">
            🚀 Warden Pipeline Execution
          </Text>
          <Text color="gray"> ({progressPercentage}%)</Text>
        </Box>
        {totalDuration && (
          <Text dimColor>Duration: {totalDuration}</Text>
        )}
      </Box>

      {/* Progress Bar */}
      <Box marginBottom={1}>
        <Text>
          {'['}
          {Array.from({length: 20}).map((_, i) => {
            const filled = i < Math.floor((completedCount / totalPhases) * 20);
            return filled ? '█' : '░';
          }).join('')}
          {']'}
        </Text>
      </Box>

      {/* Pipeline Phases */}
      <Box flexDirection="column">
        {phases.map((phase, index) => {
          const isLast = index === phases.length - 1;
          const isActive = phase.id === currentPhase;
          const config = PHASE_CONFIG[phase.id as keyof typeof PHASE_CONFIG];

          return (
            <Box key={phase.id} flexDirection="column">
              {/* Phase Line */}
              <Box>
                {/* Connection Line */}
                <Box width={2}>
                  <Text color="gray">
                    {index === 0 ? '┌' : isLast ? '└' : '├'}
                  </Text>
                </Box>

                {/* Status Icon or Spinner */}
                <Box width={3} marginRight={1}>
                  {phase.status === 'running' ? (
                    <Text color="cyan">
                      <Spinner type="dots" />
                    </Text>
                  ) : (
                    <Text color={getStatusColor(phase.status)}>
                      {getStatusIcon(phase.status)}
                    </Text>
                  )}
                </Box>

                {/* Phase Name with Icon */}
                <Box width={20}>
                  <Text color={isActive ? 'cyan' : getStatusColor(phase.status)}>
                    {config?.icon} {phase.name}
                  </Text>
                </Box>

                {/* Duration */}
                {phase.duration && (
                  <Box width={8}>
                    <Text dimColor>[{phase.duration}]</Text>
                  </Box>
                )}

                {/* Status Text */}
                <Box flexGrow={1}>
                  <Text color={getStatusColor(phase.status)}>
                    {phase.status === 'running'
                      ? `running${animationDots}`
                      : phase.status
                    }
                  </Text>
                </Box>
              </Box>

              {/* Validation SubSteps (if phase is validation and has substeps) */}
              {showDetails && phase.id === 'validation' && phase.subSteps && phase.subSteps.length > 0 && (
                <Box flexDirection="column" marginLeft={3}>
                  {phase.subSteps.map((subStep, subIndex) => {
                    const isSubActive = subStep.id === currentSubStep;
                    const isLastSub = subIndex === phase.subSteps!.length - 1;

                    return (
                      <Box key={subStep.id}>
                        {/* SubStep Connection */}
                        <Box width={2}>
                          <Text color="gray" dimColor>
                            {isLastSub ? '└' : '├'}
                          </Text>
                        </Box>

                        {/* SubStep Status */}
                        <Box width={2} marginRight={1}>
                          {subStep.status === 'running' ? (
                            <Text color="cyan">
                              <Spinner type="dots" />
                            </Text>
                          ) : (
                            <Text color={getStatusColor(subStep.status)} dimColor>
                              {getStatusIcon(subStep.status)}
                            </Text>
                          )}
                        </Box>

                        {/* SubStep Name */}
                        <Box width={15}>
                          <Text
                            color={isSubActive ? 'cyan' : getStatusColor(subStep.status)}
                            dimColor={!isSubActive}
                          >
                            {subStep.name}
                          </Text>
                        </Box>

                        {/* SubStep Duration */}
                        {subStep.duration && (
                          <Box width={8}>
                            <Text dimColor>[{subStep.duration}]</Text>
                          </Box>
                        )}

                        {/* SubStep Status */}
                        <Text
                          color={getStatusColor(subStep.status)}
                          dimColor
                        >
                          {subStep.status === 'running'
                            ? `running${animationDots}`
                            : subStep.status === 'skipped'
                            ? 'skip'
                            : ''
                          }
                        </Text>
                      </Box>
                    );
                  })}
                </Box>
              )}

              {/* Vertical connection line (except for last) */}
              {!isLast && (
                <Box>
                  <Text color="gray">│</Text>
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      {/* Summary Footer */}
      {phases.every(p => p.status !== 'pending' && p.status !== 'running') && (
        <Box marginTop={1}>
          <Text>
            Pipeline {phases.some(p => p.status === 'failed') ? (
              <Text color="red" bold>FAILED</Text>
            ) : (
              <Text color="green" bold>COMPLETED</Text>
            )}
            {totalDuration && <Text dimColor> in {totalDuration}</Text>}
          </Text>
        </Box>
      )}
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