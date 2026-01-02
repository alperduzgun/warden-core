/**
 * Scan command with real-time pipeline visualization
 * Shows 6-phase pipeline execution with live updates
 */

import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import { Box, Text, useApp } from 'ink';
import ansiEscapes from 'ansi-escapes';
import Spinner from 'ink-spinner';
import { IssueList } from '../components/IssueList.js';
import { useIPC } from '../hooks/useIPC.js';
import { ipcClient } from '../lib/ipc-client.js';
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
  verbose?: boolean;
}

export function Scan({ path, frames, verbose = false }: ScanProps) {
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
  const [showSummary, setShowSummary] = useState(false);

  // Track start time for duration calculation
  const startTimeRef = useRef<number>(0);

  // Store LLM analysis from phases
  const [llmAnalysisData, setLlmAnalysisData] = useState<Record<string, string>>({});

  // Track which phases actually executed
  const [executedPhases, setExecutedPhases] = useState<Record<string, {
    executed: boolean;
    duration?: string;
    llmUsed?: boolean;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'waiting';
    reason?: string;
  }>>({});

  // Ref to track executedPhases without triggering re-renders during pipeline execution
  const executedPhasesRef = useRef<typeof executedPhases>({});
  const pendingUpdatesRef = useRef<typeof executedPhases>({});
  const updateTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pipelineCompletedRef = useRef<boolean>(false);
  const phaseStartTimesRef = useRef<Record<string, number>>({});
  const frameStartTimesRef = useRef<Record<string, number>>({});

  // Batch state updates to reduce re-renders during pipeline execution
  const schedulePhaseUpdate = useCallback((phaseId: string, update: typeof executedPhases[string]) => {
    // If pipeline already completed, don't accept stale updates
    if (pipelineCompletedRef.current) {
      return;
    }

    // Smart merge: Don't let 'running' override 'completed'
    const existingPhase = executedPhasesRef.current[phaseId];
    if (existingPhase?.status === 'completed' && update.status === 'running') {
      // Ignore stale running update for already completed phase
      return;
    }

    // Don't accept 'completed' status for phases that never started
    // This handles backend sending phase_completed without phase_started
    if (update.status === 'completed' && !phaseStartTimesRef.current[phaseId]) {
      // Force to 'waiting' - phase never actually ran
      update = { ...update, status: 'waiting' };
    }

    // Update ref immediately for internal use
    executedPhasesRef.current = {
      ...executedPhasesRef.current,
      [phaseId]: update
    };

    // Accumulate pending updates
    pendingUpdatesRef.current = {
      ...pendingUpdatesRef.current,
      [phaseId]: update
    };

    // Debounce state updates (only update UI every 100ms during pipeline execution)
    if (updateTimerRef.current) {
      clearTimeout(updateTimerRef.current);
    }

    updateTimerRef.current = setTimeout(() => {
      setExecutedPhases(prev => ({
        ...prev,
        ...pendingUpdatesRef.current
      }));
      pendingUpdatesRef.current = {};
    }, 100);
  }, []);

  // Force immediate update (for pipeline completion)
  const flushPhaseUpdates = useCallback(() => {
    if (updateTimerRef.current) {
      clearTimeout(updateTimerRef.current);
      updateTimerRef.current = null;
    }
    if (Object.keys(pendingUpdatesRef.current).length > 0) {
      setExecutedPhases(prev => ({
        ...prev,
        ...pendingUpdatesRef.current
      }));
      pendingUpdatesRef.current = {};
    }
    // Mark pipeline as completed - no more updates will be accepted
    pipelineCompletedRef.current = true;
  }, []);

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

  // Update active frames when config is loaded or frames prop changes
  useEffect(() => {
    // If frames are provided via CLI, use them
    if (frames && frames.length > 0) {
      setActiveFrames(frames);

      // Update phases immediately
      const updatedPhases = phases.map(phase => {
        if (phase.id === 'validation') {
          return {
            ...phase,
            subSteps: frames.map((frameId: string) => ({
              id: frameId,
              name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
              status: 'pending' as PhaseStatus
            }))
          };
        }
        return phase;
      });
      setPhases(updatedPhases);
      return;
    }

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
    const framesToUse = configData?.frames_available || defaultFrames;
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
  }, [configData, configError, frames]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (updateTimerRef.current) {
        clearTimeout(updateTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!backendReady || !resolvedPath) return;

    // Use streaming endpoint for real-time progress
    const executePipeline = async () => {
      try {
        startTimeRef.current = Date.now();

        // Reset pipeline completion flag for new run
        pipelineCompletedRef.current = false;
        executedPhasesRef.current = {};
        pendingUpdatesRef.current = {};
        phaseStartTimesRef.current = {};
        frameStartTimesRef.current = {};

        // Clear classification frames and summary for fresh scan
        setClassificationFrames([]);
        setShowSummary(false);

        // Reset phases to show pipeline start
        setPhases(prev => {
          return prev.map(phase => {
            if (phase.id === 'validation') {
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

        // Ensure connected to IPC
        if (!ipcClient.isConnected()) {
          await ipcClient.connect();
        }

        // Use IPC client for streaming
        await ipcClient.sendStream('execute_pipeline_stream', {
          file_path: resolvedPath,
          // Only send frames if user explicitly specified them via CLI
          // This allows Classification phase to run and intelligently select frames
          frames: (frames && frames.length > 0) ? frames : undefined,
          verbose: verbose
        }, (event: any) => {
          // Verbose logging - write directly to stderr to not interfere with Ink UI
          if (verbose) {
            console.error(`[VERBOSE] Event received: ${JSON.stringify(event, null, 2)}`);
          }

          // Handle different event types
          if (event.type === 'progress') {
            const { event: progressEvent, data } = event;

            if (verbose) {
              console.error(`[VERBOSE] Progress event: ${progressEvent}, data:`, JSON.stringify(data, null, 2));
            }

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
              if (phaseId) {
                phaseStartTimesRef.current[phaseId] = Date.now();
                setCurrentPhase(phaseId);
                setPhases(prev => updatePhaseStatus(prev, phaseId, 'running'));
                // Track that this phase has executed
                schedulePhaseUpdate(phaseId, {
                  executed: true,
                  status: 'running' as const,
                  llmUsed: false
                });
              }
            } else if (progressEvent === 'phase_skipped') {
              const phaseName = data.phase || data.phase_name;
              const phaseId = phaseMapping[phaseName] || phaseName?.toLowerCase();
              if (phaseId) {
                setPhases(prev => updatePhaseStatus(prev, phaseId, 'skipped'));
                schedulePhaseUpdate(phaseId, {
                  executed: false,
                  status: 'skipped' as const,
                  reason: data.reason || 'disabled'
                });
              }
            } else if (progressEvent === 'phase_completed') {
              const phaseName = data.phase || data.phase_name;
              const phaseId = phaseMapping[phaseName] || phaseName?.toLowerCase();
              if (phaseId) {
                // Check if phase actually started (has a start time)
                const phaseActuallyStarted = phaseStartTimesRef.current[phaseId] !== undefined;

                // Use backend-reported duration if available (more accurate), otherwise fallback to client-side timer
                let phaseDuration = '0.0s';
                if (data.duration !== undefined && data.duration !== null) {
                  const durationVal = typeof data.duration === 'string' ? parseFloat(data.duration) : data.duration;
                  phaseDuration = `${Number(durationVal).toFixed(2)}s`;
                } else if (phaseStartTimesRef.current[phaseId]) {
                  phaseDuration = `${((Date.now() - phaseStartTimesRef.current[phaseId]) / 1000).toFixed(2)}s`;
                }

                // If phase never started (no phase_started event), mark as waiting
                // This happens when backend skips phases but sends phase_completed anyway
                // The backend should send phase_skipped instead, but it doesn't
                if (!phaseActuallyStarted) {
                  // Mark as waiting - phase didn't actually run
                  schedulePhaseUpdate(phaseId, {
                    executed: true,
                    status: 'waiting' as const,
                    llmUsed: false
                    // No duration for waiting phases
                  });
                  return;
                }

                // Capture selected frames from Classification phase
                if (phaseId === 'classification' && data.selected_frames) {
                  setClassificationFrames(data.selected_frames);

                  // Update Validation phase's subSteps: Show ALL frames that will execute
                  // Backend now merges AI-selected + User-enforced frames automatically
                  // Note: Backend returns final merged list in validation phase
                  // For now, show classification selected frames here
                  // When frame_started events arrive, they will show the full list
                  setPhases(prev => prev.map(phase => {
                    if (phase.id === 'validation') {
                      // Show frames from classification
                      // Backend will execute AI selection + User-enabled frames
                      // Frame source metadata (🤖 AI vs 👤 User) is in backend logs
                      return {
                        ...phase,
                        subSteps: data.selected_frames.map((frameId: string) => ({
                          id: frameId,
                          name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
                          status: 'pending' as PhaseStatus,
                          // Future: Add metadata.source when backend provides it
                          // metadata: { source: 'ai' | 'user', reason: string }
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

                  if (data.llm_reasoning) {
                    setLlmAnalysisData(prev => ({
                      ...prev,
                      [phaseId]: data.llm_reasoning
                    }));
                  }
                }

                schedulePhaseUpdate(phaseId, {
                  executed: true,
                  status: 'completed',
                  duration: phaseDuration,
                  llmUsed: data.llm_used || false
                });

                setPhases(prev => updatePhaseStatus(prev, phaseId, 'completed', statusMessage));
                if (currentPhase === phaseId) {
                  setCurrentPhase(undefined);
                }
              }
            } else if (progressEvent === 'frame_started') {
              const frameId = data.frame_id;
              // Track frame start time for duration calculation
              frameStartTimesRef.current[frameId] = Date.now();

              setCurrentSubStep(frameId);
              setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'running'));

              schedulePhaseUpdate(`validation_${frameId}`, {
                executed: true,
                status: 'running'
              });
            } else if (progressEvent === 'frame_completed') {
              const frameId = data.frame_id;

              // Calculate frame duration - prefer backend duration, fallback to client timer
              let frameDuration = '0.0s';
              if (data.duration !== undefined && data.duration !== null) {
                const durationVal = typeof data.duration === 'string' ? parseFloat(data.duration) : data.duration;
                frameDuration = `${Number(durationVal).toFixed(2)}s`;
              } else if (frameStartTimesRef.current[frameId]) {
                // Use client-side timer if backend didn't send duration
                frameDuration = `${((Date.now() - frameStartTimesRef.current[frameId]) / 1000).toFixed(2)}s`;
              }

              setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'completed', frameDuration));

              schedulePhaseUpdate(`validation_${frameId}`, {
                executed: true,
                status: 'completed',
                duration: frameDuration
              });

              if (currentSubStep === frameId) {
                setCurrentSubStep(undefined);
              }
            }
          } else if (event.type === 'result') {
            // Process final result
            const result = event.data;
            const elapsed = Date.now() - startTimeRef.current;

            // Flush any pending phase updates before showing results
            flushPhaseUpdates();

            // Wait 800ms for any late phase updates to arrive
            // Backend sometimes sends result before final phase_completed events
            setTimeout(() => {
              // Force all phases to final completed state for pipeline display
              setPhases(prev => prev.map(phase => {
                const executedPhase = executedPhasesRef.current[phase.id];

                // If we have execution data, sync it
                if (executedPhase) {
                  // If phase ran and finished (completed, skipped, failed) or never ran (waiting)
                  if (['completed', 'skipped', 'failed', 'waiting'].includes(executedPhase.status)) {
                    return {
                      ...phase,
                      status: executedPhase.status as PhaseStatus,
                      duration: executedPhase.duration
                    };
                  }
                }

                // Final safety net: If we have a result, nothing should be pending/running
                if (phase.status === 'pending' || phase.status === 'running') {
                  // If we are here, backend likely didn't send an event for this phase
                  // Force to 'completed' so the UI shows done
                  return { ...phase, status: 'completed' as PhaseStatus };
                }

                return phase;
              }));

              // Check if all phases that actually ran are completed
              // Don't count 'waiting' as final - those phases never ran
              const allPhasesComplete = ['pre-analysis', 'analysis', 'classification', 'validation', 'fortification', 'cleaning']
                .every(phaseId => {
                  const phase = executedPhasesRef.current[phaseId];
                  // Phase never tracked OR not executed OR completed/skipped (not waiting!)
                  return !phase || !phase.executed || ['completed', 'skipped'].includes(phase.status);
                });

              setIsWaitingForResults(false);
              setCurrentPhase(undefined);
              setCurrentSubStep(undefined);
              setShowSummary(allPhasesComplete);

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
                frame_results: result.frame_results,
                quality_score: result.quality_score,
                artifacts: result.artifacts
              });

              setTotalDuration(`${(elapsed / 1000).toFixed(1)}s`);
            }, 800);

            // Show waiting state immediately
            setIsWaitingForResults(true);
          }
        });

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

  // Dashboard-style Components
  const FindingsCards = ({ result }: { result: PipelineResult }) => (
    <Box flexDirection="row" gap={1} marginBottom={1}>
      <Box flexDirection="column" borderStyle="round" borderColor="red" paddingX={1} width={15}>
        <Text color="gray">CRITICAL</Text>
        <Text bold color="red">{result.critical_findings}</Text>
      </Box>
      <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1} width={15}>
        <Text color="gray">HIGH</Text>
        <Text bold color="yellow">{result.high_findings}</Text>
      </Box>
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} width={15}>
        <Text color="gray">MEDIUM</Text>
        <Text bold color="cyan">{result.medium_findings}</Text>
      </Box>
      <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1} width={15}>
        <Text color="gray">LOW</Text>
        <Text bold color="blue">{result.low_findings}</Text>
      </Box>
    </Box>
  );

  const MetadataDisplay = ({ result }: { result: PipelineResult }) => (
    <Box flexDirection="row" borderStyle="round" padding={1} marginBottom={1} gap={3}>
      <Box flexDirection="column">
        <Text dimColor>Duration</Text>
        <Text bold>{(result.duration).toFixed(1)}s</Text>
      </Box>
      <Box flexDirection="column">
        <Text dimColor>Quality Score</Text>
        <Text bold>{result.quality_score ? result.quality_score.toFixed(1) : '0.0'}/10</Text>
      </Box>
      <Box flexDirection="column">
        <Text dimColor>Total Findings</Text>
        <Text bold>{result.total_findings}</Text>
      </Box>
      <Box flexDirection="column">
        <Text dimColor>Status</Text>
        <Text bold color={result.status === 'success' || result.status === 'completed' || result.status == '2' ? 'green' : 'red'}>
          {String(result.status) === '2' ? 'COMPLETED' : String(result.status).toUpperCase()}
        </Text>
      </Box>
    </Box>
  );

  const ArtifactsList = ({ artifacts }: { artifacts: NonNullable<PipelineResult['artifacts']> }) => {
    if (!artifacts || artifacts.length === 0) return null;
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="gray" padding={1} marginBottom={1}>
        <Text bold>📦 ARTIFACTS</Text>
        <Box flexDirection="column" marginTop={1}>
          {artifacts.map((artifact, i) => (
            <Box key={i} flexDirection="row" justifyContent="space-between">
              <Text>📄 {artifact.name}</Text>
              <Text dimColor>{artifact.size}</Text>
            </Box>
          ))}
        </Box>
      </Box>
    );
  };



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
              compact={false}
              showDetails={true}
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
              forceState={
                // Check multiple success indicators: 'success', 'completed', or enum value 2
                (pipelineResult.status === 'success' || pipelineResult.status === 'completed' || pipelineResult.status === '2' || pipelineResult.status === 2 as unknown)
                  ? 'completed'
                  : 'failed'
              }
            />
          </Box>

          {showSummary && (
            <>
              <Box marginBottom={1}>
                <Text bold color="green">✓ Analysis Complete</Text>
                {pipelineResult.llm_analysis?.llm_enabled && (
                  <Text color="cyan"> 🤖 Enhanced with AI Analysis ({pipelineResult.llm_analysis.llm_provider})</Text>
                )}
              </Box>

              {/* Dashboard-aligned Metadata */}
              <MetadataDisplay result={pipelineResult} />

              {/* Findings Breakdown Cards */}
              <FindingsCards result={pipelineResult} />


              {/* Show comprehensive phase execution summary */}
              <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="green" padding={1}>
                <Text bold color="green">📊 Phase Execution Summary:</Text>
                <Box flexDirection="column" marginLeft={2}>
                  {['pre-analysis', 'analysis', 'classification', 'validation', 'fortification', 'cleaning'].map(phaseId => {
                    const executedPhase = executedPhases[phaseId];
                    const phaseInfo = phases.find(p => p.id === phaseId);
                    const phaseName = phaseInfo?.name || phaseId;

                    // Don't show if never executed
                    if (!executedPhase || !executedPhase.executed) {
                      return null;
                    }

                    // Use executedPhase.status as source of truth (not phases.status)
                    const displayStatus = executedPhase.status;

                    // Icon mapping for different statuses
                    const statusIcon =
                      displayStatus === 'completed' ? '✅' :
                        displayStatus === 'failed' ? '❌' :
                          displayStatus === 'skipped' ? '⊘' :
                            displayStatus === 'waiting' ? '⏳' :
                              '⏸️';

                    // Color mapping for different statuses
                    const statusColor =
                      displayStatus === 'completed' ? 'green' :
                        displayStatus === 'failed' ? 'red' :
                          displayStatus === 'skipped' ? 'gray' :
                            displayStatus === 'waiting' ? 'gray' :
                              'yellow';

                    return (
                      <Text key={phaseId}>
                        {statusIcon} {phaseName}:
                        <Text color={statusColor}>
                          {' '}{displayStatus.toUpperCase()}
                        </Text>
                        {executedPhase.duration && displayStatus === 'completed' && <Text dimColor> ({executedPhase.duration})</Text>}
                        {executedPhase.llmUsed && <Text color="cyan"> 🤖</Text>}
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

              {/* Summary Stats Plan Phase 3 */}
              <Box flexDirection="column" borderStyle="round" borderColor="green" padding={1} marginBottom={1}>
                <Text bold color="green">📈 SUMMARY</Text>
                <Box marginTop={1}>
                  <Text>Total Found: <Text bold>{pipelineResult.total_findings}</Text>  •  </Text>
                  <Text>Total Fixed: <Text bold color="green">0</Text>  •  </Text>
                  <Text>Avg Coverage: <Text bold>{
                    (pipelineResult.frame_results.reduce((acc: number, fr: any) => acc + (fr.metadata?.coverage || 0), 0) / (pipelineResult.frame_results.length || 1)).toFixed(1)
                  }%</Text></Text>
                </Box>
                <Box>
                  <Text>Passing: <Text bold color="green">{pipelineResult.frames_passed}/{pipelineResult.total_frames}</Text>  •  </Text>
                  <Text>Warnings: <Text bold color="yellow">{pipelineResult.frames_skipped}</Text>  •  </Text>
                  <Text>Failed: <Text bold color="red">{pipelineResult.frames_failed}</Text></Text>
                </Box>
              </Box>

              {/* Frame Stats Display Phase 2 */}
              <FrameStatsDisplay frames={pipelineResult.frame_results.map((fr: any) => {
                const metadata = fr.metadata || {};

                // specific check for status 
                let status: 'pass' | 'warning' | 'fail' = 'pass';
                if (fr.status === 'failed') status = 'fail';
                else if (fr.status === 'warning') status = 'warning';
                else if (fr.issues_found > 0) status = 'warning';

                return {
                  frameId: fr.frame_id,
                  name: fr.frame_name,
                  status: status,
                  duration: `${Number(fr.duration || 0).toFixed(1)}s`,
                  coverage: metadata.coverage || 0,
                  found: metadata.findings_found || fr.issues_found || 0,
                  fixed: metadata.findings_fixed || 0,
                  trend: metadata.trend || 0
                };
              })} />

              <Box flexDirection="column" marginBottom={1}>
                <Text bold>Findings Summary:</Text>
                <Text>  🔴 Critical: <Text bold color="red">{pipelineResult.critical_findings || 0}</Text></Text>
                <Text>  🟠 High: <Text bold color="redBright">{pipelineResult.high_findings || 0}</Text></Text>
                <Text>  🟡 Medium: <Text bold color="yellow">{pipelineResult.medium_findings || 0}</Text></Text>
                <Text>  ⚪ Low: <Text bold color="gray">{pipelineResult.low_findings || 0}</Text></Text>
              </Box>

              {/* Frame-level LLM Analysis Summary (e.g., Orphan Detection) */}
              {pipelineResult.frame_results.some((fr: any) => fr.metadata?.llm_filter_summary) && (
                <Box flexDirection="column" marginTop={1} marginBottom={1}>
                  <Text bold color="cyan">🔬 Frame Analysis Insights:</Text>
                  {pipelineResult.frame_results
                    .filter((fr: any) => fr.metadata?.llm_filter_summary)
                    .map((fr: any) => {
                      const summary = fr.metadata.llm_filter_summary;
                      return (
                        <Box key={fr.frame_id} flexDirection="column" marginLeft={2}>
                          <Text color="yellow">• {fr.frame_id.toUpperCase()}: </Text>
                          <Box flexDirection="column" marginLeft={2}>
                            <Text dimColor>
                              Candidates: {summary.ast_candidates_found || 0} →
                              Filtered: {summary.llm_filtered_out || 0} →
                              Final: {summary.final_findings || 0}
                            </Text>
                            {summary.reasoning && (
                              <Text dimColor wrap="wrap">💭 {summary.reasoning}</Text>
                            )}
                          </Box>
                        </Box>
                      );
                    })
                  }
                </Box>
              )}

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

              {/* Artifacts Section */}
              {pipelineResult.artifacts && pipelineResult.artifacts.length > 0 && (
                <ArtifactsList artifacts={pipelineResult.artifacts} />
              )}


              {pipelineResult.total_findings === 0 && (
                <Box marginTop={1}>
                  <Text color="green">✨ No issues found! Your code is clean.</Text>
                </Box>
              )}
            </>
          )}
        </Box>
      )}
    </Box>
  );

}

// -----------------------------------------------------------------------------
// Helper Components for Frame Statistics
// -----------------------------------------------------------------------------

interface FrameDisplayStats {
  frameId: string;
  name: string;
  status: 'pass' | 'warning' | 'fail';
  duration: string;
  coverage: number;
  found: number;
  fixed: number;
  trend: number;
}

function FrameStatsDisplay({ frames }: { frames: FrameDisplayStats[] }) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" padding={1} marginBottom={1}>
      <Text bold color="cyan">🎯 FRAME STATISTICS</Text>
      <Box flexDirection="column" marginTop={1}>
        {frames.map(frame => (
          <FrameStatItem key={frame.frameId} frame={frame} />
        ))}
      </Box>
    </Box>
  );
}

function FrameStatItem({ frame }: { frame: FrameDisplayStats }) {
  const statusIcon = frame.status === 'pass' ? '✓' :
    frame.status === 'warning' ? '⚠' : '✗';
  const statusColor = frame.status === 'pass' ? 'green' :
    frame.status === 'warning' ? 'yellow' : 'red';

  // Coverage bar (20 chars width)
  const barWidth = 20;
  const filledCount = Math.min(barWidth, Math.max(0, Math.round((frame.coverage / 100) * barWidth)));
  const emptyCount = Math.max(0, barWidth - filledCount);
  const coverageBar = '█'.repeat(filledCount) + '░'.repeat(emptyCount);

  const trendIcon = frame.trend > 0 ? '↗' : frame.trend < 0 ? '↘' : '→';

  return (
    <Box flexDirection="column" marginY={0}>
      <Box>
        <Text color={statusColor}>{statusIcon} </Text>
        <Text bold>{frame.name}</Text>
        <Text dimColor> [{frame.duration}]</Text>
      </Box>
      <Box marginLeft={2}>
        <Text dimColor>Coverage: </Text>
        <Text>{coverageBar} {frame.coverage.toFixed(0)}%</Text>
      </Box>
      <Box marginLeft={2}>
        <Text dimColor>Found: </Text>
        <Text>{frame.found}  •  </Text>
        <Text dimColor>Fixed: </Text>
        <Text color="green">{frame.fixed}  •  </Text>
        <Text dimColor>Trend: </Text>
        <Text>{frame.trend > 0 ? '+' : ''}{frame.trend}% {trendIcon}</Text>
      </Box>
    </Box>
  );
}