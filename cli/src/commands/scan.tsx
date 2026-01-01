/**
 * Scan command with real-time pipeline visualization
 * Shows 6-phase pipeline execution with live updates
 */

import React, { useEffect, useState, useRef } from 'react';
import { Box, Text, useApp } from 'ink';
import ansiEscapes from 'ansi-escapes';
import Spinner from 'ink-spinner';
import { IssueList } from '../components/IssueList.js';
import { useIPC } from '../hooks/useIPC.js';
import {
  PipelineDisplay,
  PipelinePhase,
  PhaseStatus,
  createInitialPhases,
  updatePhaseStatus,
  updateSubStepStatus
} from '../components/PipelineDisplay.js';
import { backendManager } from '../lib/backend-manager.js';
import { resolvePath, validatePath } from '../lib/path-utils.js';
import { LoadingIndicator, ConnectionStatus } from '../components/LoadingIndicator.js';
import { ErrorDisplay } from '../utils/errors.js';
import { runPreFlightChecks } from '../lib/pre-flight.js';
import type { PipelineEvent, PipelineResult, Finding, ConfigResult } from '../lib/types.js';

interface ScanProps {
  path: string;
  frames?: string[] | undefined;
}

export function Scan({ path, frames }: ScanProps) {
  const [backendReady, setBackendReady] = useState(false);
  const [isConnecting, setIsConnecting] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [resolvedPath, setResolvedPath] = useState<string>('');
  const [retryCount, setRetryCount] = useState(0);

  // Clear terminal once on mount
  useEffect(() => {
    // Use clear terminal and cursor to home
    process.stdout.write('\x1Bc');
  }, []);

  // Pipeline visualization state
  const [phases, setPhases] = useState<PipelinePhase[]>(createInitialPhases());
  const [currentPhase, setCurrentPhase] = useState<string | undefined>();
  const [currentSubStep, setCurrentSubStep] = useState<string | undefined>();
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [totalDuration, setTotalDuration] = useState<string | undefined>();
  const [activeFrames, setActiveFrames] = useState<string[]>([]);
  const [classificationFrames, setClassificationFrames] = useState<string[]>([]);
  const [isWaitingForResults, setIsWaitingForResults] = useState(false);

  // Track start time for duration calculation
  const startTimeRef = useRef<number>(0);

  // Store LLM analysis from phases
  const [llmAnalysisData, setLlmAnalysisData] = useState<Record<string, string>>({});

  // Track which phases actually executed
  const [executedPhases, setExecutedPhases] = useState<Record<string, {
    executed: boolean;
    duration?: string;
    llmUsed?: boolean;
    status: 'pending' | 'running' | 'completed' | 'failed';
  }>>({});

  // Get config to determine active frames
  const { data: configData, error: configError } = useIPC<ConfigResult>({
    command: 'get_config',
    autoExecute: backendReady,
  });

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

    // Run pre-flight checks to ensure backend is ready
    const runChecks = async () => {
      try {
        setRetryCount(0);
        const checkResult = await runPreFlightChecks('scan');

        if (checkResult.passed) {
          setBackendReady(true);
          setIsConnecting(false);
        } else {
          const failedChecks = checkResult.checks
            .filter(c => !c.passed)
            .map(c => c.name)
            .join(', ');
          setStartupError(`Pre-flight checks failed: ${failedChecks}`);
          setIsConnecting(false);
        }
      } catch (error) {
        setStartupError(error instanceof Error ? error.message : 'Pre-flight checks failed');
        setIsConnecting(false);
      }
    };

    runChecks();
  }, [path]);

  // Update active frames when config is loaded
  useEffect(() => {
    // Default frames if config fails
    const defaultFrames = ['security', 'chaos', 'orphan', 'architectural', 'stress', 'env-security', 'demo-security'];

    if (configError) {
      // Use default frames if config fails
      setActiveFrames(defaultFrames);
    } else if (configData && configData.frames_available) {
      setActiveFrames(configData.frames_available);
    } else {
      // Use default frames as fallback
      setActiveFrames(defaultFrames);
    }

    // Update initial phases with actual frames
    const framesToUse = activeFrames.length > 0 ? activeFrames : defaultFrames;
    const updatedPhases = phases.map(phase => {
      if (phase.id === 'validation' && framesToUse.length > 0) {
        return {
          ...phase,
          subSteps: framesToUse.map((frameId: string) => ({
            id: frameId,
            name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
            status: 'pending' as PhaseStatus
          }))
        };
      }
      return phase;
    });
    setPhases(updatedPhases);
  }, [configData, configError]);

  useEffect(() => {
    if (!backendReady || !resolvedPath) return;

    // Use streaming endpoint for real-time progress
    const executePipeline = async () => {
      try {
        startTimeRef.current = Date.now();
        const phaseStartTimes: Record<string, number> = {};

        // Clear classification frames for fresh scan
        setClassificationFrames([]);

        // Reset phases to show pipeline start
        setPhases(prev => {
          return prev.map(phase => {
            if (phase.id === 'validation') {
              // Use classification frames if available, otherwise use activeFrames
              const framesToShow = classificationFrames.length > 0
                ? classificationFrames
                : (activeFrames.length > 0 ? activeFrames : ['security', 'chaos', 'orphan']);

              return {
                ...phase,
                status: 'pending' as PhaseStatus,
                subSteps: framesToShow.map(frameId => ({
                  id: frameId,
                  name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
                  status: 'pending' as PhaseStatus
                }))
              };
            }
            return { ...phase, status: 'pending' as PhaseStatus };
          });
        });

        // Use EventSource for Server-Sent Events
        const response = await fetch('http://localhost:6173/rpc', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'execute_pipeline_stream',
            params: {
              path: resolvedPath
            },
            id: Date.now()
          })
        });

        if (!response.ok) {
          throw new Error(`Backend error: ${response.statusText}`);
        }

        if (!response.body) {
          throw new Error('No response body');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process SSE events from buffer
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const eventData = line.slice(6);
              try {
                const event = JSON.parse(eventData);

                // Handle different event types
                if (event.type === 'progress') {
                  const { event: progressEvent, data } = event;

                  // Map backend phase names to frontend phase IDs
                  const phaseMapping: Record<string, string> = {
                    'PRE_ANALYSIS': 'pre-analysis',
                    'ANALYSIS': 'analysis',
                    'CLASSIFICATION': 'classification',
                    'VALIDATION': 'validation',
                    'FORTIFICATION': 'fortification',
                    'CLEANING': 'cleaning'
                  };

                  if (progressEvent === 'phase_started') {
                    const phaseName = data.phase || data.phase_name;
                    const phaseId = phaseMapping[phaseName] || phaseName?.toLowerCase();
                    console.log('[DEBUG] Phase started:', { phaseName, phaseId, data });
                    if (phaseId) {
                      phaseStartTimes[phaseId] = Date.now();
                      setCurrentPhase(phaseId);
                      setPhases(prev => updatePhaseStatus(prev, phaseId, 'running'));
                      // Track that this phase has executed
                      setExecutedPhases(prev => {
                        const newState = {
                          ...prev,
                          [phaseId]: {
                            executed: true,
                            status: 'running' as const,
                            llmUsed: false
                          }
                        };
                        console.log('[DEBUG] Updated executedPhases:', newState);
                        return newState;
                      });
                    }
                  } else if (progressEvent === 'phase_completed') {
                    const phaseName = data.phase || data.phase_name;
                    const phaseId = phaseMapping[phaseName] || phaseName?.toLowerCase();
                    if (phaseId) {
                      // Use backend-reported duration if available (more accurate), otherwise fallback to client-side timer
                      let phaseDuration = '0.0s';
                      if (data.duration !== undefined && data.duration !== null) {
                        const durationVal = typeof data.duration === 'string' ? parseFloat(data.duration) : data.duration;
                        phaseDuration = `${Number(durationVal).toFixed(2)}s`;
                      } else if (phaseStartTimes[phaseId]) {
                        phaseDuration = `${((Date.now() - phaseStartTimes[phaseId]) / 1000).toFixed(2)}s`;
                      }

                      // Capture selected frames from Classification phase
                      if (phaseId === 'classification' && data.selected_frames) {
                        setClassificationFrames(data.selected_frames);

                        // Immediately update Validation phase's subSteps with Classification results
                        setPhases(prev => prev.map(phase => {
                          if (phase.id === 'validation') {
                            return {
                              ...phase,
                              subSteps: data.selected_frames.map((frameId: string) => ({
                                id: frameId,
                                name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
                                status: 'pending' as PhaseStatus
                              }))
                            };
                          }
                          return phase;
                        }));
                      }

                      // Check if LLM was used and show it
                      let statusMessage = phaseDuration;
                      if (data.llm_used) {
                        statusMessage = `${phaseDuration} (🤖 AI)`;

                        // Store LLM reasoning for later display
                        if (data.llm_reasoning) {
                          setLlmAnalysisData(prev => ({
                            ...prev,
                            [phaseId]: data.llm_reasoning
                          }));
                        }
                      }

                      // Track phase completion details
                      setExecutedPhases(prev => ({
                        ...prev,
                        [phaseId]: {
                          executed: true,
                          status: 'completed',
                          duration: phaseDuration,
                          llmUsed: data.llm_used || false
                        }
                      }));

                      setPhases(prev => updatePhaseStatus(prev, phaseId, 'completed', statusMessage));
                      if (currentPhase === phaseId) {
                        setCurrentPhase(undefined);
                      }
                    }
                  } else if (progressEvent === 'frame_started') {
                    const frameId = data.frame_id;
                    setCurrentSubStep(frameId);
                    setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'running'));

                    // Track that this frame actually executed
                    setExecutedPhases(prev => ({
                      ...prev,
                      [`validation_${frameId}`]: {
                        executed: true,
                        status: 'running'
                      }
                    }));
                  } else if (progressEvent === 'frame_completed') {
                    const frameId = data.frame_id;
                    const frameDuration = data.duration ? `${Number(data.duration).toFixed(2)}s` : '0.0s';
                    setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'completed', frameDuration));

                    // Track that this frame completed
                    setExecutedPhases(prev => ({
                      ...prev,
                      [`validation_${frameId}`]: {
                        executed: true,
                        status: 'completed',
                        duration: frameDuration
                      }
                    }));

                    if (currentSubStep === frameId) {
                      setCurrentSubStep(undefined);
                    }
                  }
                } else if (event.type === 'result') {
                  // Process final result
                  const result = event.data;
                  const elapsed = Date.now() - startTimeRef.current;

                  setIsWaitingForResults(false);
                  setCurrentPhase(undefined);
                  setCurrentSubStep(undefined);

                  // Extract LLM analysis info
                  const llmInfo = result.llm_analysis || {
                    llm_enabled: result.context_summary?.llm_used || false,
                    llm_provider: result.context_summary?.llm_provider || 'none',
                    phases_with_llm: result.context_summary?.phases_with_llm || [],
                    llm_quality_score: result.context_summary?.quality_score,
                    llm_confidence: result.context_summary?.confidence,
                    llm_reasoning: result.context_summary?.reasoning
                  };

                  setPipelineResult({
                    pipeline_id: result.pipeline_id,
                    pipeline_name: result.pipeline_name,
                    status: result.status,
                    duration: result.duration || elapsed,
                    total_frames: result.total_frames,
                    frames_passed: result.frames_passed,
                    frames_failed: result.frames_failed,
                    frames_skipped: result.frames_skipped,
                    total_findings: result.total_findings,
                    critical_findings: result.critical_findings,
                    high_findings: result.high_findings,
                    medium_findings: result.medium_findings,
                    low_findings: result.low_findings,
                    llm_analysis: llmInfo,
                    frame_results: result.frame_results
                  });

                  setTotalDuration(`${(elapsed / 1000).toFixed(1)}s`);
                }
              } catch (e) {
                console.error('Error parsing SSE event:', e, eventData);
              }
            } else if (line.startsWith('event: error')) {
              // Handle error event
              const nextLine = lines[lines.indexOf(line) + 1];
              if (nextLine && nextLine.startsWith('data: ')) {
                const errorData = JSON.parse(nextLine.slice(6));
                setPipelineError(errorData.error || 'Pipeline execution failed');
                setIsWaitingForResults(false);
              }
            } else if (line.startsWith('event: complete')) {
              // Pipeline complete
              setIsWaitingForResults(false);
            }
          }
        }

      } catch (error) {
        setPipelineError(error instanceof Error ? error.message : 'Pipeline execution failed');
        setIsWaitingForResults(false);
        setCurrentPhase(undefined);
        setCurrentSubStep(undefined);
      }
    };

    executePipeline();
  }, [backendReady, resolvedPath, frames, activeFrames]);

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

  // Show loading while backend starts
  if (!backendReady) {
    return (
      <LoadingIndicator
        message="Starting Warden backend"
        subMessage="Initializing Python services..."
        showTimer={true}
        timeoutWarning={15}
      />
    );
  }


  // Show pipeline visualization
  return (
    <Box flexDirection="column">
      {/* Pipeline Display - only show while running */}
      {!pipelineResult && !pipelineError && !isWaitingForResults && (
        <PipelineDisplay
          phases={phases}
          currentPhase={currentPhase}
          currentSubStep={currentSubStep}
          totalDuration={totalDuration}
          showDetails={true}
        />
      )}

      {/* Show waiting message when pipeline is complete but waiting for results */}
      {isWaitingForResults && !pipelineResult && !pipelineError && (
        <Box flexDirection="column">
          <Box marginBottom={1}>
            <PipelineDisplay
              phases={phases}
              totalDuration={totalDuration}
              compact={true}
            />
          </Box>
          <Box>
            <Text color="cyan">
              <Spinner type="dots" /> Analyzing results and generating report...
            </Text>
          </Box>
        </Box>
      )}

      {/* Show error if pipeline failed */}
      {pipelineError && (
        <Box marginTop={1}>
          <Text color="red" bold>❌ Pipeline Error: {pipelineError}</Text>
        </Box>
      )}

      {/* Show results when pipeline completes */}
      {pipelineResult && (
        <Box flexDirection="column">
          {/* Compact pipeline summary */}
          <Box marginBottom={1}>
            <PipelineDisplay
              phases={phases}
              totalDuration={totalDuration}
              compact={true}
            />
          </Box>

          <Box marginBottom={1}>
            <Text bold color="green">✓ Analysis Complete</Text>
            {pipelineResult.llm_analysis?.llm_enabled && (
              <Text color="cyan"> 🤖 Enhanced with AI Analysis ({pipelineResult.llm_analysis.llm_provider})</Text>
            )}
          </Box>

          {/* Show comprehensive phase execution summary */}
          <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="green" padding={1}>
            <Text bold color="green">📊 Phase Execution Summary:</Text>
            <Box flexDirection="column" marginLeft={2}>
              {['pre-analysis', 'analysis', 'classification', 'validation', 'fortification', 'cleaning'].map(phaseId => {
                const phase = executedPhases[phaseId];
                const phaseInfo = phases.find(p => p.id === phaseId);
                const phaseName = phaseInfo?.name || phaseId;

                console.log('[DEBUG] Phase summary:', { phaseId, phase, executed: phase?.executed });

                if (!phase || !phase.executed) {
                  return (
                    <Text key={phaseId} dimColor>
                      ⏭️  {phaseName}: <Text color="gray">SKIPPED</Text>
                    </Text>
                  );
                }

                return (
                  <Text key={phaseId}>
                    {phase.status === 'completed' ? '✅' : phase.status === 'failed' ? '❌' : '⏸️'} {phaseName}:
                    <Text color={phase.status === 'completed' ? 'green' : phase.status === 'failed' ? 'red' : 'yellow'}>
                      {' '}{phase.status.toUpperCase()}
                    </Text>
                    {phase.duration && <Text dimColor> ({phase.duration})</Text>}
                    {phase.llmUsed && <Text color="cyan"> 🤖</Text>}
                    {phaseId === 'classification' && classificationFrames.length > 0 && (
                      <Text dimColor> → Selected frames: {classificationFrames.join(', ')}</Text>
                    )}
                    {phaseId === 'validation' && (
                      <Text dimColor> → Executed frames: {
                        Object.keys(executedPhases)
                          .filter(key => key.startsWith('validation_'))
                          .map(key => key.replace('validation_', ''))
                          .join(', ') || 'none'
                      }</Text>
                    )}
                  </Text>
                );
              })}
            </Box>
          </Box>

          {/* Show LLM Analysis Details if available */}
          {pipelineResult.llm_analysis?.llm_enabled && (
            <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="cyan" padding={1}>
              <Text bold color="cyan">🤖 AI-Powered Analysis:</Text>
              {pipelineResult.llm_analysis.llm_quality_score && (
                <Text>  📊 Code Quality Score: <Text bold color={
                  pipelineResult.llm_analysis.llm_quality_score >= 7 ? "green" :
                    pipelineResult.llm_analysis.llm_quality_score >= 5 ? "yellow" : "red"
                }>{pipelineResult.llm_analysis.llm_quality_score.toFixed(1)}/10</Text></Text>
              )}
              {pipelineResult.llm_analysis.llm_confidence && (
                <Text>  🎯 AI Confidence: <Text bold color="cyan">{(pipelineResult.llm_analysis.llm_confidence * 100).toFixed(0)}%</Text></Text>
              )}
              {pipelineResult.llm_analysis.phases_with_llm && pipelineResult.llm_analysis.phases_with_llm.length > 0 && (
                <Text>  ✨ AI-Enhanced Phases: <Text color="cyan">{pipelineResult.llm_analysis.phases_with_llm.join(', ')}</Text></Text>
              )}
              {pipelineResult.llm_analysis.llm_reasoning && (
                <Box marginTop={1}>
                  <Text dimColor>  💭 AI Reasoning: {pipelineResult.llm_analysis.llm_reasoning}</Text>
                </Box>
              )}
              {/* Show collected LLM analysis from phases */}
              {Object.keys(llmAnalysisData).length > 0 && (
                <Box marginTop={1} flexDirection="column">
                  <Text bold color="cyan">  📝 AI Phase Insights:</Text>
                  {Object.entries(llmAnalysisData).map(([phase, reasoning]) => (
                    <Box key={phase} marginLeft={2}>
                      <Text color="yellow">• {phase}: </Text>
                      <Text dimColor>{String(reasoning).slice(0, 100)}...</Text>
                    </Box>
                  ))}
                </Box>
              )}
            </Box>
          )}

          <Box flexDirection="column" marginBottom={1}>
            <Text>Frames: <Text bold color="green">{pipelineResult.frames_passed} passed</Text>
              {pipelineResult.frames_failed > 0 && <Text bold color="red">, {pipelineResult.frames_failed} failed</Text>}
              {pipelineResult.frames_skipped > 0 && <Text bold color="gray">, {pipelineResult.frames_skipped} skipped</Text>}
              <Text dimColor> ({activeFrames.length} total)</Text>
            </Text>
          </Box>

          <Box flexDirection="column" marginBottom={1}>
            <Text bold>Findings Summary:</Text>
            <Text>  🔴 Critical: <Text bold color="red">{pipelineResult.critical_findings || 0}</Text></Text>
            <Text>  🟠 High: <Text bold color="redBright">{pipelineResult.high_findings || 0}</Text></Text>
            <Text>  🟡 Medium: <Text bold color="yellow">{pipelineResult.medium_findings || 0}</Text></Text>
            <Text>  ⚪ Low: <Text bold color="gray">{pipelineResult.low_findings || 0}</Text></Text>
          </Box>

          {/* Convert findings to issues for IssueList compatibility */}
          {pipelineResult.total_findings > 0 && (
            <Box flexDirection="column">
              <Box marginBottom={1}>
                <Text bold>Issues Found:</Text>
              </Box>
              <IssueList
                issues={
                  pipelineResult.frame_results.flatMap(frame =>
                    frame.findings.map((finding: Finding, idx: number) => ({
                      id: `${frame.frame_id}_${idx}`,
                      filePath: finding.file || resolvedPath,
                      line: finding.line || 0,
                      column: finding.column || 0,
                      severity: finding.severity as 'critical' | 'high' | 'medium' | 'low',
                      message: finding.message,
                      rule: finding.code || 'unknown',
                      frame: frame.frame_id
                    }))
                  )
                }
              />
            </Box>
          )}

          {pipelineResult.total_findings === 0 && (
            <Box marginTop={1}>
              <Text color="green">✨ No issues found! Your code is clean.</Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}