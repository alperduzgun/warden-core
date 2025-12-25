/**
 * AdvancedInput Component
 * Simple wrapper around TextInput with visual hints
 * Note: Advanced shortcuts are handled in ChatInterfaceEnhanced to avoid useInput conflicts
 */

import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';

export interface AdvancedInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  isDisabled?: boolean;
}

/**
 * Simple text input with hints
 */
export function AdvancedInput({
  value,
  onChange,
  onSubmit,
  placeholder = 'Type...',
  isDisabled = false,
}: AdvancedInputProps) {
  return (
    <Box flexDirection="column">
      <TextInput
        value={value}
        onChange={onChange}
        onSubmit={onSubmit}
        placeholder={isDisabled ? 'Processing...' : placeholder}
        showCursor={!isDisabled}
      />
      {/* Shortcut hints when empty */}
      {value.length === 0 && !isDisabled && (
        <Box marginTop={0}>
          <Text dimColor>
            /: commands | @: files | ↑↓: history | Ctrl+P: palette
          </Text>
        </Box>
      )}
    </Box>
  );
}
