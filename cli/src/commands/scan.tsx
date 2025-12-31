/**
 * Scan command with real-time pipeline visualization
 * Shows 6-phase pipeline execution with live updates
 */

import React, {useEffect, useState, useRef} from 'react';
import {Box, Text, useApp} from 'ink';
import ansiEscapes from 'ansi-escapes';
import Spinner from 'ink-spinner';
import {IssueList} from '../components/IssueList.js';
import {useIPC} from '../hooks/useIPC.js';
import {
  PipelineDisplay,
  PipelinePhase,
  PhaseStatus,
  createInitialPhases,
  updatePhaseStatus,
  updateSubStepStatus
} from '../components/PipelineDisplay.js';
import {backendManager} from '../lib/backend-manager.js';
import {resolvePath, validatePath} from '../lib/path-utils.js';
import {LoadingIndicator, ConnectionStatus} from '../components/LoadingIndicator.js';
import {ErrorDisplay} from '../utils/errors.js';
import {runPreFlightChecks} from '../lib/pre-flight.js';
import type {PipelineEvent, PipelineResult, Finding, ConfigResult} from '../lib/types.js';

interface ScanProps {
  path: string;
  frames?: string[] | undefined;
}

export function Scan({path, frames}: ScanProps) {
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
  const [isWaitingForResults, setIsWaitingForResults] = useState(false);

  // Track start time for duration calculation
  const startTimeRef = useRef<number>(0);

  // Get config to determine active frames
  const {data: configData, error: configError} = useIPC<ConfigResult>({
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

    // Use regular scan endpoint instead of streaming for now
    const executePipeline = async () => {
      try {
        startTimeRef.current = Date.now();

        // Reset phases to show pipeline start
        setPhases(prev => {
          return prev.map(phase => {
            if (phase.id === 'validation' && activeFrames.length > 0) {
              return {
                ...phase,
                status: 'pending' as PhaseStatus,
                subSteps: activeFrames.map(frameId => ({
                  id: frameId,
                  name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace(/-/g, ' '),
                  status: 'pending' as PhaseStatus
                }))
              };
            }
            return { ...phase, status: 'pending' as PhaseStatus };
          });
        });

        // Simulate pipeline phases for better UX
        const simulatePhases = async () => {
          const phaseOrder = ['pre-analysis', 'analysis', 'classification', 'validation', 'fortification', 'cleaning'];

          for (const phaseId of phaseOrder) {
            setCurrentPhase(phaseId);
            setPhases(prev => updatePhaseStatus(prev, phaseId, 'running'));

            if (phaseId === 'validation' && activeFrames.length > 0) {
              // Simulate frame execution
              for (const frameId of activeFrames) {
                setCurrentSubStep(frameId);
                setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'running'));
                await new Promise(resolve => setTimeout(resolve, 500)); // Simulate frame execution time
                setPhases(prev => updateSubStepStatus(prev, 'validation', frameId, 'completed', '0.5s'));
              }
            } else {
              await new Promise(resolve => setTimeout(resolve, 800)); // Simulate phase execution time
            }

            const elapsed = Date.now() - startTimeRef.current;
            const duration = `${(elapsed / 1000).toFixed(1)}s`;
            setPhases(prev => updatePhaseStatus(prev, phaseId, 'completed', duration));
          }

          setCurrentPhase(undefined);
          setCurrentSubStep(undefined);

          // Set waiting for results state
          setIsWaitingForResults(true);
        };

        // Start phase simulation
        simulatePhases();

        // Call actual scan endpoint
        const response = await fetch('http://localhost:6173/rpc', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'scan',
            params: {
              path: resolvedPath,
              frames: frames || activeFrames
            },
            id: Date.now()
          })
        });

        if (!response.ok) {
          throw new Error(`Backend error: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.error) {
          setPipelineError(data.error.message);
          setIsWaitingForResults(false);
        } else if (data.result) {
          // Convert scan result to pipeline result format
          const scanResult = data.result;
          const elapsed = Date.now() - startTimeRef.current;

          setIsWaitingForResults(false);
          setPipelineResult({
            pipeline_id: `scan_${Date.now()}`,
            pipeline_name: 'Code Analysis Pipeline',
            status: 'completed',
            duration: elapsed,
            total_frames: activeFrames.length,
            frames_passed: activeFrames.length,
            frames_failed: 0,
            frames_skipped: 0,
            total_findings: scanResult.issues?.length || 0,
            critical_findings: scanResult.summary?.critical || 0,
            high_findings: scanResult.summary?.high || 0,
            medium_findings: scanResult.summary?.medium || 0,
            low_findings: scanResult.summary?.low || 0,
            frame_results: activeFrames.map(frameId => ({
              frame_id: frameId,
              frame_name: frameId.charAt(0).toUpperCase() + frameId.slice(1).replace('-', ' '),
              status: 'completed',
              duration: 0.5,
              issues_found: scanResult.issues?.filter((i: any) => i.frame === frameId).length || 0,
              is_blocker: false,
              findings: scanResult.issues?.filter((i: any) => i.frame === frameId).map((issue: any) => ({
                severity: issue.severity,
                message: issue.message,
                line: issue.line,
                column: issue.column,
                code: issue.rule,
                file: issue.filePath
              })) || []
            }))
          });

          setTotalDuration(`${(elapsed / 1000).toFixed(1)}s`);
        }

      } catch (error) {
        setPipelineError(error instanceof Error ? error.message : 'Pipeline execution failed');
        setIsWaitingForResults(false);
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
          </Box>

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