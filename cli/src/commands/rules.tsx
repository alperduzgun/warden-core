/**
 * Rules command - Interactive rule manager
 * Manage frame rules with expand/collapse and CRUD operations
 */

import React, {useState, useEffect} from 'react';
import {Box, Text, useInput, useApp} from 'ink';
import SelectInput from 'ink-select-input';
import {Spinner} from '../components/Spinner.js';
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

interface RulesData {
  frame_rules: Record<string, FrameRule>;
  rules: any[];
  global_rules: string[];
}

type NavigationLevel = 'frame' | 'pre_rules' | 'post_rules';
type ModalType = 'none' | 'add_rule' | 'confirm_delete';

interface NavigationState {
  level: NavigationLevel;
  frameIndex: number;
  ruleIndex: number;
}

export function Rules({onExit}: RulesProps = {}) {
  const {exit} = useApp();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rulesData, setRulesData] = useState<RulesData | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Navigation state
  const [expandedFrames, setExpandedFrames] = useState<Set<string>>(new Set());
  const [nav, setNav] = useState<NavigationState>({
    level: 'frame',
    frameIndex: 0,
    ruleIndex: 0,
  });

  // Modal state
  const [modalType, setModalType] = useState<ModalType>('none');
  const [ruleToDelete, setRuleToDelete] = useState<{frame: string; rule: string; position: 'pre' | 'post'} | null>(null);

  useEffect(() => {
    loadRules();
  }, []);

  // Auto-clear messages after 3 seconds
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 3000);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [message]);

  const loadRules = async () => {
    try {
      setIsLoading(true);
      setError(null);

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

  const saveRules = async (newRulesData: RulesData) => {
    try {
      const rulesPath = path.join(process.cwd(), '.warden', 'rules.yaml');
      const rulesContent = await fs.readFile(rulesPath, 'utf-8');
      const rulesYaml = yaml.load(rulesContent) as any;

      // Update frame_rules only
      rulesYaml.frame_rules = newRulesData.frame_rules;

      // Write back
      await fs.writeFile(rulesPath, yaml.dump(rulesYaml, {indent: 2, lineWidth: -1}));
      setRulesData(newRulesData);
    } catch (err) {
      setMessage(`❌ Failed to save: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const handleDeleteRule = async (confirmed: boolean) => {
    if (!confirmed || !ruleToDelete || !rulesData) {
      setModalType('none');
      setRuleToDelete(null);
      return;
    }

    const {frame, rule, position} = ruleToDelete;
    const newRulesData = {...rulesData};
    const frameRule = {...newRulesData.frame_rules[frame]};

    if (position === 'pre') {
      frameRule.pre_rules = (frameRule.pre_rules || []).filter((r) => r !== rule);
    } else {
      frameRule.post_rules = (frameRule.post_rules || []).filter((r) => r !== rule);
    }

    newRulesData.frame_rules[frame] = frameRule;

    await saveRules(newRulesData);
    setMessage(`✅ Removed ${rule} from ${frame}/${position}_rules`);
    setModalType('none');
    setRuleToDelete(null);
  };

  const handleMoveRule = async () => {
    if (!rulesData || nav.level === 'frame') return;

    const currentFrame = frameRuleEntries[nav.frameIndex];
    if (!currentFrame) return;

    const [frameName, frameRule] = currentFrame;
    const isInPre = nav.level === 'pre_rules';
    const sourceRules = isInPre ? (frameRule.pre_rules || []) : (frameRule.post_rules || []);
    const ruleToMove = sourceRules[nav.ruleIndex];

    if (!ruleToMove) return;

    const newRulesData = {...rulesData};
    const newFrameRule = {...newRulesData.frame_rules[frameName]};

    if (isInPre) {
      // Move from pre to post
      newFrameRule.pre_rules = (newFrameRule.pre_rules || []).filter((r) => r !== ruleToMove);
      newFrameRule.post_rules = [...(newFrameRule.post_rules || []), ruleToMove];
      setNav({...nav, level: 'post_rules', ruleIndex: newFrameRule.post_rules.length - 1});
    } else {
      // Move from post to pre
      newFrameRule.post_rules = (newFrameRule.post_rules || []).filter((r) => r !== ruleToMove);
      newFrameRule.pre_rules = [...(newFrameRule.pre_rules || []), ruleToMove];
      setNav({...nav, level: 'pre_rules', ruleIndex: newFrameRule.pre_rules.length - 1});
    }

    newRulesData.frame_rules[frameName] = newFrameRule;

    await saveRules(newRulesData);
    setMessage(`✅ Moved ${ruleToMove}: ${isInPre ? 'pre → post' : 'post → pre'}`);
  };

  const handleAddRule = async (ruleId: string) => {
    if (!rulesData || nav.level === 'frame') return;

    const currentFrame = frameRuleEntries[nav.frameIndex];
    if (!currentFrame) return;

    const [frameName, frameRule] = currentFrame;
    const position = nav.level === 'pre_rules' ? 'pre' : 'post';

    const newRulesData = {...rulesData};
    const newFrameRule = {...newRulesData.frame_rules[frameName]};

    if (position === 'pre') {
      newFrameRule.pre_rules = [...(newFrameRule.pre_rules || []), ruleId];
    } else {
      newFrameRule.post_rules = [...(newFrameRule.post_rules || []), ruleId];
    }

    newRulesData.frame_rules[frameName] = newFrameRule;

    await saveRules(newRulesData);
    setMessage(`✅ Added ${ruleId} to ${frameName}/${position}_rules`);
    setModalType('none');
  };

  const frameRuleEntries = Object.entries(rulesData?.frame_rules || {});
  const currentFrame = frameRuleEntries[nav.frameIndex];
  const currentFrameName = currentFrame?.[0];
  const currentFrameRules = currentFrame?.[1];

  // Get available rules for picker (excluding already added)
  const getAvailableRules = () => {
    if (!rulesData || !currentFrameRules) return [];

    const existingRules = new Set([
      ...(currentFrameRules.pre_rules || []),
      ...(currentFrameRules.post_rules || []),
    ]);

    return (rulesData.rules || [])
      .filter((rule: any) => !existingRules.has(rule.id))
      .map((rule: any) => ({
        label: `${rule.id} (${rule.category}, ${rule.severity})`,
        value: rule.id,
      }));
  };

  // Keyboard controls - Main navigation
  useInput((input, key) => {
    if (!rulesData || frameRuleEntries.length === 0) return;

    // Modal handlers
    if (modalType === 'confirm_delete') {
      if (input === 'y' || input === 'Y') {
        handleDeleteRule(true);
      } else if (input === 'n' || input === 'N' || key.escape) {
        handleDeleteRule(false);
      }
      return;
    }

    if (modalType === 'add_rule') {
      if (key.escape) {
        setModalType('none');
      }
      return; // SelectInput handles its own keys
    }

    // Expand/collapse frame
    if (key.rightArrow && nav.level === 'frame' && currentFrameName) {
      setExpandedFrames((prev) => new Set(prev).add(currentFrameName));
      const preRules = currentFrameRules?.pre_rules || [];
      if (preRules.length > 0) {
        setNav({...nav, level: 'pre_rules', ruleIndex: 0});
      } else {
        const postRules = currentFrameRules?.post_rules || [];
        if (postRules.length > 0) {
          setNav({...nav, level: 'post_rules', ruleIndex: 0});
        }
      }
      return;
    }

    if (key.leftArrow && nav.level !== 'frame') {
      setNav({...nav, level: 'frame'});
      return;
    }

    // Delete rule
    if ((input === 'd' || key.delete || key.backspace) && nav.level !== 'frame') {
      const isInPre = nav.level === 'pre_rules';
      const sourceRules = isInPre ? (currentFrameRules?.pre_rules || []) : (currentFrameRules?.post_rules || []);
      const ruleToRemove = sourceRules[nav.ruleIndex];

      if (ruleToRemove && currentFrameName) {
        setRuleToDelete({
          frame: currentFrameName,
          rule: ruleToRemove,
          position: isInPre ? 'pre' : 'post',
        });
        setModalType('confirm_delete');
      }
      return;
    }

    // Move rule
    if (input === 'm' && nav.level !== 'frame') {
      handleMoveRule();
      return;
    }

    // Add rule
    if ((input === '+' || key.return) && nav.level !== 'frame') {
      setModalType('add_rule');
      return;
    }

    // Navigate up/down
    if (key.upArrow) {
      if (nav.level === 'frame') {
        setNav({...nav, frameIndex: Math.max(0, nav.frameIndex - 1)});
      } else if (nav.level === 'pre_rules') {
        const preRules = currentFrameRules?.pre_rules || [];
        if (nav.ruleIndex > 0) {
          setNav({...nav, ruleIndex: nav.ruleIndex - 1});
        } else {
          setNav({...nav, level: 'frame'});
        }
      } else if (nav.level === 'post_rules') {
        const postRules = currentFrameRules?.post_rules || [];
        if (nav.ruleIndex > 0) {
          setNav({...nav, ruleIndex: nav.ruleIndex - 1});
        } else {
          const preRules = currentFrameRules?.pre_rules || [];
          if (preRules.length > 0) {
            setNav({...nav, level: 'pre_rules', ruleIndex: preRules.length - 1});
          } else {
            setNav({...nav, level: 'frame'});
          }
        }
      }
      return;
    }

    if (key.downArrow) {
      if (nav.level === 'frame') {
        if (nav.frameIndex < frameRuleEntries.length - 1) {
          setNav({...nav, frameIndex: nav.frameIndex + 1});
        }
      } else if (nav.level === 'pre_rules') {
        const preRules = currentFrameRules?.pre_rules || [];
        if (nav.ruleIndex < preRules.length - 1) {
          setNav({...nav, ruleIndex: nav.ruleIndex + 1});
        } else {
          const postRules = currentFrameRules?.post_rules || [];
          if (postRules.length > 0) {
            setNav({...nav, level: 'post_rules', ruleIndex: 0});
          } else if (nav.frameIndex < frameRuleEntries.length - 1) {
            setNav({...nav, level: 'frame', frameIndex: nav.frameIndex + 1});
          }
        }
      } else if (nav.level === 'post_rules') {
        const postRules = currentFrameRules?.post_rules || [];
        if (nav.ruleIndex < postRules.length - 1) {
          setNav({...nav, ruleIndex: nav.ruleIndex + 1});
        } else if (nav.frameIndex < frameRuleEntries.length - 1) {
          setNav({...nav, level: 'frame', frameIndex: nav.frameIndex + 1});
        }
      }
      return;
    }

    // Exit
    if (input === 'q' || key.escape) {
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

  // Show rule picker modal
  if (modalType === 'add_rule') {
    const availableRules = getAvailableRules();

    if (availableRules.length === 0) {
      setModalType('none');
      setMessage('❌ No available rules to add');
      return null;
    }

    return (
      <Box flexDirection="column">
        <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
          <Text bold color="cyan">
            Add Rule to {currentFrameName}/{nav.level === 'pre_rules' ? 'pre' : 'post'}_rules
          </Text>
        </Box>
        <Box marginTop={1} paddingX={2}>
          <Text dimColor>[↑↓] Select  [Enter] Add  [Esc] Cancel</Text>
        </Box>
        <Box marginTop={1}>
          <SelectInput
            items={availableRules}
            onSelect={(item) => handleAddRule(item.value)}
          />
        </Box>
      </Box>
    );
  }

  // Show delete confirmation modal
  if (modalType === 'confirm_delete' && ruleToDelete) {
    return (
      <Box flexDirection="column">
        <Box borderStyle="round" borderColor="red" paddingX={2} paddingY={1}>
          <Text bold color="red">
            Confirm Delete
          </Text>
        </Box>
        <Box marginTop={1} paddingX={2} flexDirection="column">
          <Text>Remove <Text bold color="cyan">{ruleToDelete.rule}</Text></Text>
          <Text>from <Text bold>{ruleToDelete.frame}/{ruleToDelete.position}_rules</Text>?</Text>
        </Box>
        <Box marginTop={1} paddingX={2}>
          <Text dimColor>[y] Yes  [n] Cancel</Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text bold color="cyan">
          Warden Rules Manager
        </Text>
      </Box>

      {/* Message */}
      {message && (
        <Box marginTop={1}>
          <Text>{message}</Text>
        </Box>
      )}

      {/* Global Rules */}
      {rulesData.global_rules.length > 0 && (
        <Box marginTop={1}>
          <Text>
            Global rules: <Text bold color="yellow">{rulesData.global_rules.join(', ')}</Text>
          </Text>
        </Box>
      )}

      {/* Frame Rules List */}
      <Box marginTop={1} borderStyle="round" borderColor="gray" flexDirection="column">
        {frameRuleEntries.map(([frameName, frameRule], frameIdx) => {
          const isFrameSelected = nav.level === 'frame' && nav.frameIndex === frameIdx;
          const isFrameExpanded = expandedFrames.has(frameName);
          const preRules = frameRule.pre_rules || [];
          const postRules = frameRule.post_rules || [];
          const onFail = frameRule.on_fail || 'continue';

          return (
            <Box key={frameName} flexDirection="column" paddingX={2} paddingY={1}>
              {/* Frame header */}
              <Box>
                <Text color={isFrameSelected ? 'cyan' : 'white'}>
                  {isFrameExpanded ? '▼' : '▶'}{' '}
                </Text>
                <Text bold color={isFrameSelected ? 'cyan' : 'white'}>
                  {frameName}
                </Text>
                <Text dimColor> · </Text>
                <Text color={onFail === 'stop' ? 'red' : 'yellow'}>
                  on_fail: {onFail}
                </Text>
                <Text dimColor> · </Text>
                <Text dimColor>
                  {preRules.length + postRules.length} rules
                </Text>
              </Box>

              {/* Expanded view */}
              {isFrameExpanded && (
                <Box flexDirection="column" marginLeft={2} marginTop={1}>
                  {/* Pre-rules */}
                  <Box flexDirection="column">
                    <Text bold color="green">
                      Pre-rules ({preRules.length}):
                    </Text>
                    {preRules.length > 0 ? (
                      preRules.map((ruleId, ruleIdx) => {
                        const isSelected =
                          nav.level === 'pre_rules' &&
                          nav.frameIndex === frameIdx &&
                          nav.ruleIndex === ruleIdx;

                        return (
                          <Box key={ruleId} marginLeft={2}>
                            <Text color={isSelected ? 'cyan' : 'white'}>
                              {isSelected ? '▶' : ' '}{' '}
                            </Text>
                            <Text color="green">✓</Text>
                            <Text color={isSelected ? 'white' : 'gray'}> {ruleId}</Text>
                          </Box>
                        );
                      })
                    ) : (
                      <Box marginLeft={2}>
                        <Text dimColor>  (no pre-rules)</Text>
                      </Box>
                    )}
                  </Box>

                  {/* Post-rules */}
                  <Box flexDirection="column" marginTop={1}>
                    <Text bold color="blue">
                      Post-rules ({postRules.length}):
                    </Text>
                    {postRules.length > 0 ? (
                      postRules.map((ruleId, ruleIdx) => {
                        const isSelected =
                          nav.level === 'post_rules' &&
                          nav.frameIndex === frameIdx &&
                          nav.ruleIndex === ruleIdx;

                        return (
                          <Box key={ruleId} marginLeft={2}>
                            <Text color={isSelected ? 'cyan' : 'white'}>
                              {isSelected ? '▶' : ' '}{' '}
                            </Text>
                            <Text color="blue">✓</Text>
                            <Text color={isSelected ? 'white' : 'gray'}> {ruleId}</Text>
                          </Box>
                        );
                      })
                    ) : (
                      <Box marginLeft={2}>
                        <Text dimColor>  (no post-rules)</Text>
                      </Box>
                    )}
                  </Box>
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      {/* Controls */}
      <Box marginTop={1}>
        <Text dimColor>
          {nav.level === 'frame'
            ? '[↑↓] Navigate  [→] Expand  [q/Esc] Back'
            : '[↑↓] Navigate  [←] Collapse  [d] Delete  [m] Move  [+/Enter] Add  [q/Esc] Back'}
        </Text>
      </Box>

      {/* Stats */}
      <Box marginTop={1}>
        <Text dimColor>
          {frameRuleEntries.length} frames · {rulesData.rules.length} total rules · {expandedFrames.size} expanded
        </Text>
      </Box>
    </Box>
  );
}
