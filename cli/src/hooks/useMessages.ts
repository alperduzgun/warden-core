/**
 * Custom hook for managing chat messages
 */

import { useState, useCallback } from 'react';
import { Message, MessageType, StreamingState } from '../types/index.js';

/**
 * Simple unique ID generator
 */
const generateId = (): string => {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

export interface UseMessagesReturn {
  messages: Message[];
  addMessage: (content: string, type: MessageType, metadata?: Record<string, unknown>) => Message;
  updateMessage: (id: string, content: string) => void;
  deleteMessage: (id: string) => void;
  clearMessages: () => void;
  startStreaming: (type: MessageType) => string;
  updateStreaming: (id: string, content: string) => void;
  completeStreaming: (id: string) => void;
  streamingState: StreamingState;
}

/**
 * Hook for managing messages state
 */
export function useMessages(initialMessages: Message[] = []): UseMessagesReturn {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [streamingState, setStreamingState] = useState<StreamingState>(StreamingState.IDLE);

  /**
   * Add a new message
   */
  const addMessage = useCallback((
    content: string,
    type: MessageType,
    metadata?: Record<string, unknown>
  ): Message => {
    const message: Message = {
      id: generateId(),
      type,
      content,
      timestamp: new Date(),
      ...(metadata !== undefined && { metadata }),
    };

    setMessages((prev) => [...prev, message]);
    return message;
  }, []);

  /**
   * Update an existing message
   */
  const updateMessage = useCallback((id: string, content: string) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === id ? { ...msg, content } : msg))
    );
  }, []);

  /**
   * Delete a message
   */
  const deleteMessage = useCallback((id: string) => {
    setMessages((prev) => prev.filter((msg) => msg.id !== id));
  }, []);

  /**
   * Clear all messages
   */
  const clearMessages = useCallback(() => {
    setMessages([]);
    setStreamingState(StreamingState.IDLE);
  }, []);

  /**
   * Start streaming a new message
   */
  const startStreaming = useCallback((type: MessageType): string => {
    const message: Message = {
      id: generateId(),
      type,
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    };

    setMessages((prev) => [...prev, message]);
    setStreamingState(StreamingState.STREAMING);
    return message.id;
  }, []);

  /**
   * Update streaming message content
   */
  const updateStreaming = useCallback((id: string, content: string) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === id ? { ...msg, content, isStreaming: true } : msg
      )
    );
  }, []);

  /**
   * Complete streaming message
   */
  const completeStreaming = useCallback((id: string) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === id ? { ...msg, isStreaming: false } : msg
      )
    );
    setStreamingState(StreamingState.COMPLETE);
  }, []);

  return {
    messages,
    addMessage,
    updateMessage,
    deleteMessage,
    clearMessages,
    startStreaming,
    updateStreaming,
    completeStreaming,
    streamingState,
  };
}
