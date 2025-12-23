/**
 * Component Exports
 *
 * Central export point for all UI components
 */

export { Header } from './Header.js';
export { ChatArea } from './ChatArea.js';
export { InputBox } from './InputBox.js';
export { StreamingMessage } from './StreamingMessage.js';

// Progress & Streaming Components
export { WardenSpinner, StatusSpinner } from './WardenSpinner.js';
export { ProgressIndicator, CompactProgress } from './ProgressIndicator.js';
export {
  FrameStatusDisplay,
  FrameSummary,
} from './FrameStatusDisplay.js';
export { IssueSummary, SeverityIndicator } from './IssueSummary.js';
export { ScanProgress, CompactScanProgress } from './ScanProgress.js';

// Type exports
export type { HeaderProps } from './Header.js';
export type { ChatAreaProps } from './ChatArea.js';
export type { InputBoxProps } from './InputBox.js';
export type { StreamingMessageProps } from '../types/index.js';
export type { WardenSpinnerProps, StatusSpinnerProps } from './WardenSpinner.js';
export type {
  ProgressIndicatorProps,
  CompactProgressProps,
} from './ProgressIndicator.js';
export type {
  FrameStatusDisplayProps,
  FrameProgress,
  FrameStatus,
  FrameSummaryProps,
} from './FrameStatusDisplay.js';
export type {
  IssueSummaryProps,
  SeverityIndicatorProps,
} from './IssueSummary.js';
