/**
 * Business logic hooks for Rules Manager
 */

import {useState, useEffect} from 'react';
import fs from 'fs/promises';
import path from 'path';
import YAML from 'yaml';
import type {
  RulesData,
  HistoryEntry,
  NavigationState,
  ModalType,
  RuleToDelete,
  FrameRule,
} from './rules-types.js';

export function useRulesManager() {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rulesData, setRulesData] = useState<RulesData | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Undo/Redo history (max 50 entries)
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Navigation state
  const [expandedFrames, setExpandedFrames] = useState<Set<string>>(new Set());
  const [nav, setNav] = useState<NavigationState>({
    level: 'frame',
    frameIndex: 0,
    ruleIndex: 0,
  });

  // Modal state
  const [modalType, setModalType] = useState<ModalType>('none');
  const [ruleToDelete, setRuleToDelete] = useState<RuleToDelete | null>(null);

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
      const rulesYaml = YAML.parse(rulesContent) as any;

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

  const saveRules = async (newRulesData: RulesData, action: string = 'Change') => {
    try {
      const rulesPath = path.join(process.cwd(), '.warden', 'rules.yaml');
      const rulesContent = await fs.readFile(rulesPath, 'utf-8');

      // Parse with comment preservation
      const rulesDoc = YAML.parseDocument(rulesContent);

      // Clean up empty arrays before saving
      const cleanedFrameRules = {...newRulesData.frame_rules};
      Object.keys(cleanedFrameRules).forEach((frameName) => {
        const frameRule = cleanedFrameRules[frameName];
        if (!frameRule) return;

        // Remove empty pre_rules arrays
        if (frameRule.pre_rules && frameRule.pre_rules.length === 0) {
          delete frameRule.pre_rules;
        }

        // Remove empty post_rules arrays
        if (frameRule.post_rules && frameRule.post_rules.length === 0) {
          delete frameRule.post_rules;
        }
      });

      // Update frame_rules while preserving structure and comments
      rulesDoc.set('frame_rules', cleanedFrameRules);

      // Write back with preserved formatting and comments
      await fs.writeFile(rulesPath, rulesDoc.toString());
      setRulesData({...newRulesData, frame_rules: cleanedFrameRules});

      // Add to history (truncate future history if we're not at the end)
      const newHistory = history.slice(0, historyIndex + 1);
      newHistory.push({
        frame_rules: JSON.parse(JSON.stringify(cleanedFrameRules)),
        timestamp: Date.now(),
        action,
      });

      // Keep only last 50 entries
      if (newHistory.length > 50) {
        newHistory.shift();
      }

      setHistory(newHistory);
      setHistoryIndex(newHistory.length - 1);
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

    await saveRules(newRulesData, `Delete ${rule}`);
    setMessage(`✅ Removed ${rule} from ${frame}/${position}_rules`);
    setModalType('none');
    setRuleToDelete(null);
  };

  const handleMoveRule = async (
    frameRuleEntries: [string, FrameRule][],
  ) => {
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

    await saveRules(newRulesData, `Move ${ruleToMove}`);
    setMessage(`✅ Moved ${ruleToMove}: ${isInPre ? 'pre → post' : 'post → pre'}`);
  };

  const handleAddRule = async (
    ruleId: string,
    frameRuleEntries: [string, FrameRule][],
  ) => {
    if (!rulesData || nav.level === 'frame') return;

    const currentFrame = frameRuleEntries[nav.frameIndex];
    if (!currentFrame) return;

    const [frameName, frameRule] = currentFrame;
    const position = nav.level === 'pre_rules' ? 'pre' : 'post';

    // Duplicate check
    const existingRules = [
      ...(frameRule.pre_rules || []),
      ...(frameRule.post_rules || []),
    ];

    if (existingRules.includes(ruleId)) {
      setMessage(`❌ Rule ${ruleId} already exists in ${frameName}`);
      setModalType('none');
      return;
    }

    const newRulesData = {...rulesData};
    const newFrameRule = {...newRulesData.frame_rules[frameName]};

    if (position === 'pre') {
      newFrameRule.pre_rules = [...(newFrameRule.pre_rules || []), ruleId];
    } else {
      newFrameRule.post_rules = [...(newFrameRule.post_rules || []), ruleId];
    }

    newRulesData.frame_rules[frameName] = newFrameRule;

    await saveRules(newRulesData, `Add ${ruleId}`);
    setMessage(`✅ Added ${ruleId} to ${frameName}/${position}_rules`);
    setModalType('none');
  };

  const handleUndo = async () => {
    if (historyIndex <= 0 || !rulesData) {
      setMessage('❌ Nothing to undo');
      return;
    }

    const prevEntry = history[historyIndex - 1];
    if (!prevEntry) {
      setMessage('❌ History entry not found');
      return;
    }

    const currentAction = history[historyIndex];
    const rulesPath = path.join(process.cwd(), '.warden', 'rules.yaml');
    const rulesContent = await fs.readFile(rulesPath, 'utf-8');
    const rulesDoc = YAML.parseDocument(rulesContent);

    rulesDoc.set('frame_rules', prevEntry.frame_rules);
    await fs.writeFile(rulesPath, rulesDoc.toString());

    setRulesData({
      ...rulesData,
      frame_rules: prevEntry.frame_rules,
    });
    setHistoryIndex(historyIndex - 1);
    setMessage(`↶ Undo: ${currentAction?.action || 'Change'}`);
  };

  const handleRedo = async () => {
    if (historyIndex >= history.length - 1 || !rulesData) {
      setMessage('❌ Nothing to redo');
      return;
    }

    const nextEntry = history[historyIndex + 1];
    if (!nextEntry) {
      setMessage('❌ History entry not found');
      return;
    }

    const rulesPath = path.join(process.cwd(), '.warden', 'rules.yaml');
    const rulesContent = await fs.readFile(rulesPath, 'utf-8');
    const rulesDoc = YAML.parseDocument(rulesContent);

    rulesDoc.set('frame_rules', nextEntry.frame_rules);
    await fs.writeFile(rulesPath, rulesDoc.toString());

    setRulesData({
      ...rulesData,
      frame_rules: nextEntry.frame_rules,
    });
    setHistoryIndex(historyIndex + 1);
    setMessage(`↷ Redo: ${nextEntry.action}`);
  };

  return {
    // State
    isLoading,
    error,
    rulesData,
    message,
    expandedFrames,
    nav,
    modalType,
    ruleToDelete,

    // State setters
    setExpandedFrames,
    setNav,
    setModalType,
    setRuleToDelete,
    setMessage,

    // Actions
    loadRules,
    handleDeleteRule,
    handleMoveRule,
    handleAddRule,
    handleUndo,
    handleRedo,
  };
}

export function getAvailableRules(
  rulesData: RulesData | null,
  currentFrameRules: FrameRule | undefined,
) {
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
}
