/**
 * Rules command - Display validation rules from rules.yaml
 * Shows frame rules and individual rule definitions
 */

import React, {useState, useEffect} from 'react';
import {Box, Text, useInput, useApp} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {backendManager} from '../utils/backendManager.js';
import {ipcClient} from '../lib/ipc-client.js';
import fs from 'fs/promises';
import path from 'path';
import yaml from 'js-yaml';

interface RulesProps {
  onExit?: () => void;
}

interface FrameRule {
  pre_rules?: string[];
  post_rules?: string[];
  on_fail?: string;
}

interface Rule {
  id: string;
  name: string;
  category: string;
  severity: string;
  isBlocker: boolean;
  description: string;
  enabled: boolean;
}

interface RulesData {
  frame_rules: Record<string, FrameRule>;
  rules: Rule[];
  global_rules: string[];
}

export function Rules({onExit}: RulesProps = {}) {
  const {exit} = useApp();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rulesData, setRulesData] = useState<RulesData | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [viewMode, setViewMode] = useState<'frames' | 'rules'>('frames');

  useEffect(() => {
    loadRules();
  }, []);

  const loadRules = async () => {
    try {
      setIsLoading(true);
      setError(null);

      // Read rules.yaml directly from .warden directory
      const rulesPath = path.join(process.cwd(), '.warden', 'rules.yaml');
      const rulesContent = await fs.readFile(rulesPath, 'utf-8');
      const rulesYaml = yaml.load(rulesContent) as any;

      setRulesData({
        frame_rules: rulesYaml.frame_rules || {},
        rules: rulesYaml.rules || [],
        global_rules: rulesYaml.global_rules || [],
      });

      setIsLoading(false);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load rules: ${errorMsg}`);
      setIsLoading(false);
    }
  };

  // Keyboard controls
  useInput((input, key) => {
    if (key.upArrow) {
      const maxIndex = viewMode === 'frames'
        ? Object.keys(rulesData?.frame_rules || {}).length - 1
        : (rulesData?.rules.length || 0) - 1;
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : maxIndex));
    } else if (key.downArrow) {
      const maxIndex = viewMode === 'frames'
        ? Object.keys(rulesData?.frame_rules || {}).length - 1
        : (rulesData?.rules.length || 0) - 1;
      setSelectedIndex((prev) => (prev < maxIndex ? prev + 1 : 0));
    } else if (key.tab) {
      // Toggle between frames and rules view
      setViewMode((prev) => (prev === 'frames' ? 'rules' : 'frames'));
      setSelectedIndex(0);
    } else if (input === 'q' || key.escape) {
      // Exit rules UI (back to chat if callback provided, otherwise exit app)
      if (onExit) {
        onExit();
      } else {
        exit();
      }
    }
  });

  if (isLoading) {
    return <Spinner message="Loading rules..." />;
  }

  if (error) {
    return (
      <Box flexDirection="column">
        <Text color="red">✗ Failed to load rules</Text>
        <Text dimColor>Error: {error}</Text>
        <Text dimColor>Make sure .warden/rules.yaml exists</Text>
      </Box>
    );
  }

  if (!rulesData) {
    return (
      <Box flexDirection="column">
        <Text color="yellow">No rules found</Text>
        <Text dimColor>Check your Warden configuration</Text>
      </Box>
    );
  }

  const frameRuleEntries = Object.entries(rulesData.frame_rules);

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text bold color="cyan">
          Warden Rules Viewer
        </Text>
      </Box>

      {/* Tab navigation */}
      <Box marginTop={1}>
        <Text>
          <Text bold color={viewMode === 'frames' ? 'cyan' : 'gray'}>
            [Frame Rules]
          </Text>
          <Text dimColor>  </Text>
          <Text bold color={viewMode === 'rules' ? 'cyan' : 'gray'}>
            [Individual Rules]
          </Text>
          <Text dimColor>  (tab to switch)</Text>
        </Text>
      </Box>

      {/* Global Rules */}
      {rulesData.global_rules.length > 0 && (
        <Box marginTop={1}>
          <Text>
            Global rules: <Text bold color="yellow">{rulesData.global_rules.join(', ')}</Text>
          </Text>
        </Box>
      )}

      {/* Content */}
      {viewMode === 'frames' ? (
        <Box marginTop={1} borderStyle="round" borderColor="gray" flexDirection="column">
          {frameRuleEntries.map(([frameName, frameRule], index) => {
            const isSelected = index === selectedIndex;
            const preRules = frameRule.pre_rules || [];
            const postRules = frameRule.post_rules || [];
            const onFail = frameRule.on_fail || 'continue';

            return (
              <Box key={frameName} paddingX={2} paddingY={1}>
                <Box flexDirection="column" width="100%">
                  {/* Frame name */}
                  <Box>
                    <Text color={isSelected ? 'cyan' : 'white'}>
                      {isSelected ? '▶' : ' '}{' '}
                    </Text>
                    <Text bold color={isSelected ? 'cyan' : 'white'}>
                      {frameName}
                    </Text>
                    <Text dimColor> · </Text>
                    <Text color={onFail === 'stop' ? 'red' : 'yellow'}>
                      on_fail: {onFail}
                    </Text>
                  </Box>

                  {/* Pre-rules */}
                  {preRules.length > 0 && (
                    <Box marginTop={1}>
                      <Text dimColor>  Pre-rules: </Text>
                      <Text color="green">{preRules.join(', ')}</Text>
                    </Box>
                  )}

                  {/* Post-rules */}
                  {postRules.length > 0 && (
                    <Box marginTop={1}>
                      <Text dimColor>  Post-rules: </Text>
                      <Text color="blue">{postRules.join(', ')}</Text>
                    </Box>
                  )}

                  {/* No rules configured */}
                  {preRules.length === 0 && postRules.length === 0 && (
                    <Box marginTop={1}>
                      <Text dimColor>  (no rules configured)</Text>
                    </Box>
                  )}
                </Box>
              </Box>
            );
          })}
        </Box>
      ) : (
        <Box marginTop={1} borderStyle="round" borderColor="gray" flexDirection="column">
          {rulesData.rules.slice(0, 10).map((rule, index) => {
            const isSelected = index === selectedIndex;

            return (
              <Box key={rule.id} paddingX={2} paddingY={1}>
                <Box flexDirection="column" width="100%">
                  {/* Rule ID and name */}
                  <Box>
                    <Text color={isSelected ? 'cyan' : 'white'}>
                      {isSelected ? '▶' : ' '}{' '}
                    </Text>
                    <Text bold color={isSelected ? 'cyan' : 'white'}>
                      {rule.id}
                    </Text>
                    {rule.isBlocker && (
                      <>
                        <Text dimColor> · </Text>
                        <Text bold color="red">
                          ⚠ BLOCKER
                        </Text>
                      </>
                    )}
                  </Box>

                  {/* Rule details */}
                  <Box marginTop={1}>
                    <Text dimColor>  {rule.name}</Text>
                  </Box>
                  <Box>
                    <Text dimColor>  </Text>
                    <Text color="yellow">{rule.category}</Text>
                    <Text dimColor> · </Text>
                    <Text color={rule.severity === 'critical' ? 'red' : rule.severity === 'high' ? 'yellow' : 'blue'}>
                      {rule.severity}
                    </Text>
                    <Text dimColor> · </Text>
                    <Text color={rule.enabled ? 'green' : 'gray'}>
                      {rule.enabled ? 'enabled' : 'disabled'}
                    </Text>
                  </Box>
                </Box>
              </Box>
            );
          })}
          {rulesData.rules.length > 10 && (
            <Box paddingX={2}>
              <Text dimColor>... and {rulesData.rules.length - 10} more rules</Text>
            </Box>
          )}
        </Box>
      )}

      {/* Controls */}
      <Box marginTop={1}>
        <Text dimColor>
          [↑↓] Navigate  [Tab] Switch view  [q/Esc] {onExit ? 'Back' : 'Quit'}
        </Text>
      </Box>

      {/* Stats */}
      <Box marginTop={1}>
        <Text dimColor>
          Total: {frameRuleEntries.length} frame rules, {rulesData.rules.length} individual rules
        </Text>
      </Box>
    </Box>
  );
}
