/**
 * Keyboard Shortcuts Configuration
 *
 * Defines all keyboard shortcuts for Warden CLI
 * Inspired by Qwen Code's keyboard shortcuts system
 */

/**
 * Command enum for all available keyboard shortcuts
 */
export enum Command {
  // Basic navigation
  HOME = 'home',                    // Ctrl+A - Move to start of line
  END = 'end',                      // Ctrl+E - Move to end of line

  // Text deletion
  CLEAR_INPUT = 'clearInput',       // Ctrl+C - Clear current input
  CLEAR_LINE = 'clearLine',         // Ctrl+U - Clear entire line
  CLEAR_SCREEN = 'clearScreen',     // Ctrl+K or Ctrl+L - Clear screen

  // Exit
  EXIT = 'exit',                    // Ctrl+C (when input is empty) or Ctrl+D

  // Submission
  SUBMIT = 'submit',                // Enter

  // Navigation (for file picker and command list)
  ARROW_UP = 'arrowUp',            // Arrow Up
  ARROW_DOWN = 'arrowDown',        // Arrow Down

  // Completion
  TAB = 'tab',                     // Tab - Accept suggestion
}

/**
 * Key binding structure
 */
export interface KeyBinding {
  /** The key name (e.g., 'a', 'return', 'tab', 'escape') */
  key?: string;
  /** Control key requirement */
  ctrl?: boolean;
  /** Shift key requirement */
  shift?: boolean;
  /** Meta/Command key requirement */
  meta?: boolean;
}

/**
 * Configuration type mapping commands to their key bindings
 */
export type KeyBindingConfig = {
  readonly [C in Command]: readonly KeyBinding[];
};

/**
 * Default Warden key bindings
 */
export const defaultKeyBindings: KeyBindingConfig = {
  // Basic navigation
  [Command.HOME]: [
    { key: 'a', ctrl: true },
  ],
  [Command.END]: [
    { key: 'e', ctrl: true },
  ],

  // Text deletion
  [Command.CLEAR_INPUT]: [
    { key: 'c', ctrl: true },        // Ctrl+C
  ],
  [Command.CLEAR_LINE]: [
    { key: 'u', ctrl: true },        // Ctrl+U
  ],
  [Command.CLEAR_SCREEN]: [
    { key: 'k', ctrl: true },        // Ctrl+K
    { key: 'l', ctrl: true },        // Ctrl+L
  ],

  // Exit
  [Command.EXIT]: [
    { key: 'd', ctrl: true },        // Ctrl+D
  ],

  // Submission
  [Command.SUBMIT]: [
    { key: 'return', ctrl: false, shift: false },
  ],

  // Navigation
  [Command.ARROW_UP]: [
    { key: 'up' },
  ],
  [Command.ARROW_DOWN]: [
    { key: 'down' },
  ],

  // Completion
  [Command.TAB]: [
    { key: 'tab' },
  ],
};

/**
 * Key type from Ink useInput
 */
export interface Key {
  name?: string;
  sequence?: string;
  ctrl: boolean;
  shift: boolean;
  meta: boolean;
  escape: boolean;
  upArrow: boolean;
  downArrow: boolean;
  leftArrow: boolean;
  rightArrow: boolean;
  tab: boolean;
  return: boolean;
  delete: boolean;
  backspace: boolean;
}

/**
 * Check if a key matches a key binding
 */
export function matchKeyBinding(keyBinding: KeyBinding, key: Key): boolean {
  // Check key name match
  if (keyBinding.key !== undefined) {
    const keyMatches = keyBinding.key === key.name;
    if (!keyMatches) {
      return false;
    }
  }

  // Check modifiers
  if (keyBinding.ctrl !== undefined && key.ctrl !== keyBinding.ctrl) {
    return false;
  }

  if (keyBinding.shift !== undefined && key.shift !== keyBinding.shift) {
    return false;
  }

  if (keyBinding.meta !== undefined && key.meta !== keyBinding.meta) {
    return false;
  }

  return true;
}

/**
 * Check if a key matches a command
 */
export function matchCommand(
  command: Command,
  key: Key,
  config: KeyBindingConfig = defaultKeyBindings
): boolean {
  const bindings = config[command];
  return bindings.some((binding) => matchKeyBinding(binding, key));
}

/**
 * Key matcher function type
 */
export type KeyMatcher = (key: Key) => boolean;

/**
 * Type for key matchers mapped to Command enum
 */
export type KeyMatchers = {
  readonly [C in Command]: KeyMatcher;
};

/**
 * Create key matchers from config
 */
export function createKeyMatchers(
  config: KeyBindingConfig = defaultKeyBindings
): KeyMatchers {
  const matchers = {} as { [C in Command]: KeyMatcher };

  for (const command of Object.values(Command)) {
    matchers[command] = (key: Key) => matchCommand(command, key, config);
  }

  return matchers as KeyMatchers;
}

/**
 * Default key matchers
 */
export const keyMatchers: KeyMatchers = createKeyMatchers(defaultKeyBindings);
