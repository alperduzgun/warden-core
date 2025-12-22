/**
 * Custom hook for managing input state and command detection
 */

import { useState, useCallback, useEffect } from 'react';
import { CommandDetection, CommandType } from '../types/index.js';
import { detectCommand, getAutocompleteSuggestions } from '../utils/commandDetector.js';

export interface UseInputReturn {
  value: string;
  setValue: (value: string) => void;
  commandDetection: CommandDetection;
  suggestions: ReturnType<typeof getAutocompleteSuggestions>;
  handleSubmit: () => void;
  clear: () => void;
}

/**
 * Hook for managing input state with command detection
 */
export function useInput(
  onSubmit?: (value: string, detection: CommandDetection) => void
): UseInputReturn {
  const [value, setValue] = useState('');
  const [commandDetection, setCommandDetection] = useState<CommandDetection>({
    type: CommandType.NONE,
    raw: '',
  });
  const [suggestions, setSuggestions] = useState<ReturnType<typeof getAutocompleteSuggestions>>([]);

  /**
   * Update command detection when value changes
   */
  useEffect(() => {
    const detection = detectCommand(value);
    setCommandDetection(detection);

    // Update suggestions
    if (detection.type !== CommandType.NONE) {
      setSuggestions(getAutocompleteSuggestions(value));
    } else {
      setSuggestions([]);
    }
  }, [value]);

  /**
   * Handle form submission
   */
  const handleSubmit = useCallback(() => {
    if (value.trim() && onSubmit) {
      onSubmit(value, commandDetection);
      setValue('');
    }
  }, [value, commandDetection, onSubmit]);

  /**
   * Clear input
   */
  const clear = useCallback(() => {
    setValue('');
  }, []);

  return {
    value,
    setValue,
    commandDetection,
    suggestions,
    handleSubmit,
    clear,
  };
}
