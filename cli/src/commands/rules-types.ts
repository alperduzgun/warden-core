/**
 * Type definitions for Rules Manager
 */

export interface RulesProps {
  onExit?: () => void;
}

export interface FrameRule {
  pre_rules?: string[];
  post_rules?: string[];
  on_fail?: string;
}

export interface RulesData {
  frame_rules: Record<string, FrameRule>;
  rules: any[];
  global_rules: string[];
}

export interface HistoryEntry {
  frame_rules: Record<string, FrameRule>;
  timestamp: number;
  action: string;
}

export type NavigationLevel = 'frame' | 'pre_rules' | 'post_rules';
export type ModalType = 'none' | 'add_rule' | 'confirm_delete';

export interface NavigationState {
  level: NavigationLevel;
  frameIndex: number;
  ruleIndex: number;
}

export interface RuleToDelete {
  frame: string;
  rule: string;
  position: 'pre' | 'post';
}
