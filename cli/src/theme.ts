/**
 * Warden CLI Theme Configuration
 *
 * Defines the color scheme and visual styling for the Warden CLI interface.
 * Inspired by Qwen Code but adapted for Warden's security-focused identity.
 */

import { ThemeColors, GradientColors } from './types/index.js';

/**
 * Warden brand colors - Security and protection themed
 */
export const WARDEN_COLORS = {
  // Primary brand colors
  shield: '#4A90E2', // Blue - shield/protection
  guardian: '#7B68EE', // Purple - guardian/vigilance
  secure: '#2ECC71', // Green - secure/safe
  warning: '#F39C12', // Orange - warnings
  critical: '#E74C3C', // Red - critical issues

  // UI colors
  background: '#1E1E1E',
  foreground: '#E0E0E0',
  muted: '#6C757D',
  border: '#444444',

  // Syntax highlighting
  keyword: '#569CD6',
  string: '#CE9178',
  number: '#B5CEA8',
  comment: '#6A9955',
  function: '#DCDCAA',
  variable: '#9CDCFE',
} as const;

/**
 * Default theme configuration
 */
export const defaultTheme: ThemeColors = {
  primary: WARDEN_COLORS.shield,
  secondary: WARDEN_COLORS.guardian,
  accent: WARDEN_COLORS.guardian,
  success: WARDEN_COLORS.secure,
  warning: WARDEN_COLORS.warning,
  error: WARDEN_COLORS.critical,
  info: WARDEN_COLORS.shield,
  background: WARDEN_COLORS.background,
  foreground: WARDEN_COLORS.foreground,
  muted: WARDEN_COLORS.muted,
  border: WARDEN_COLORS.border,
};

/**
 * Gradient colors for the header title
 * Shield blue -> Guardian purple
 */
export const titleGradient: GradientColors = [
  WARDEN_COLORS.shield,
  WARDEN_COLORS.guardian,
];

/**
 * Message type color mapping
 */
export const messageColors = {
  user: WARDEN_COLORS.shield,
  assistant: WARDEN_COLORS.foreground,
  system: WARDEN_COLORS.muted,
  error: WARDEN_COLORS.critical,
  success: WARDEN_COLORS.secure,
  warning: WARDEN_COLORS.warning,
} as const;

/**
 * Status indicator colors
 */
export const statusColors = {
  connected: WARDEN_COLORS.secure,
  disconnected: WARDEN_COLORS.muted,
  error: WARDEN_COLORS.critical,
  processing: WARDEN_COLORS.warning,
} as const;

/**
 * Command detection colors
 */
export const commandColors = {
  slash: WARDEN_COLORS.shield,
  mention: WARDEN_COLORS.guardian,
  alert: WARDEN_COLORS.critical,
  none: WARDEN_COLORS.foreground,
} as const;

/**
 * Syntax highlighting colors for code blocks
 */
export const syntaxColors = {
  keyword: WARDEN_COLORS.keyword,
  string: WARDEN_COLORS.string,
  number: WARDEN_COLORS.number,
  comment: WARDEN_COLORS.comment,
  function: WARDEN_COLORS.function,
  variable: WARDEN_COLORS.variable,
  operator: WARDEN_COLORS.foreground,
  punctuation: WARDEN_COLORS.muted,
} as const;

/**
 * Border styles
 */
export const borderStyles = {
  single: 'single',
  double: 'double',
  round: 'round',
  bold: 'bold',
  classic: 'classic',
} as const;

/**
 * Get theme instance
 */
export const getTheme = (): ThemeColors => defaultTheme;

/**
 * Theme context for components
 */
export interface ThemeContext {
  colors: ThemeColors;
  gradient: GradientColors;
  messageColors: typeof messageColors;
  statusColors: typeof statusColors;
  commandColors: typeof commandColors;
  syntaxColors: typeof syntaxColors;
}

/**
 * Create theme context with all styling information
 */
export const createThemeContext = (): ThemeContext => ({
  colors: defaultTheme,
  gradient: titleGradient,
  messageColors,
  statusColors,
  commandColors,
  syntaxColors,
});

export default defaultTheme;
