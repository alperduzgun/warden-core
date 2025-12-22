/**
 * Unit tests for useMessages hook
 */

import { describe, it, expect, beforeEach } from '@jest/globals';
import { renderHook, act } from '@testing-library/react-hooks';
import { useMessages } from '../useMessages.js';
import { MessageType, StreamingState } from '../../types/index.js';

describe('useMessages', () => {
  describe('initialization', () => {
    it('should initialize with empty messages', () => {
      const { result } = renderHook(() => useMessages());
      expect(result.current.messages).toEqual([]);
      expect(result.current.streamingState).toBe(StreamingState.IDLE);
    });

    it('should accept initial messages', () => {
      const initialMessages = [
        {
          id: '1',
          type: MessageType.SYSTEM,
          content: 'Welcome',
          timestamp: new Date(),
        },
      ];
      const { result } = renderHook(() => useMessages(initialMessages));
      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].content).toBe('Welcome');
    });
  });

  describe('addMessage', () => {
    it('should add a new message', () => {
      const { result } = renderHook(() => useMessages());

      act(() => {
        result.current.addMessage('Hello', MessageType.USER);
      });

      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].content).toBe('Hello');
      expect(result.current.messages[0].type).toBe(MessageType.USER);
    });

    it('should add message with metadata', () => {
      const { result } = renderHook(() => useMessages());

      act(() => {
        result.current.addMessage('Hello', MessageType.USER, { foo: 'bar' });
      });

      expect(result.current.messages[0].metadata).toEqual({ foo: 'bar' });
    });

    it('should generate unique IDs', () => {
      const { result } = renderHook(() => useMessages());

      act(() => {
        result.current.addMessage('Message 1', MessageType.USER);
        result.current.addMessage('Message 2', MessageType.USER);
      });

      const ids = result.current.messages.map((m) => m.id);
      expect(new Set(ids).size).toBe(2); // All unique
    });

    it('should return the created message', () => {
      const { result } = renderHook(() => useMessages());

      let message;
      act(() => {
        message = result.current.addMessage('Test', MessageType.USER);
      });

      expect(message).toBeDefined();
      expect(message?.content).toBe('Test');
    });
  });

  describe('updateMessage', () => {
    it('should update message content', () => {
      const { result } = renderHook(() => useMessages());

      let messageId: string;
      act(() => {
        const msg = result.current.addMessage('Original', MessageType.USER);
        messageId = msg.id;
      });

      act(() => {
        result.current.updateMessage(messageId, 'Updated');
      });

      expect(result.current.messages[0].content).toBe('Updated');
    });

    it('should not affect other messages', () => {
      const { result } = renderHook(() => useMessages());

      let id1: string, id2: string;
      act(() => {
        id1 = result.current.addMessage('Message 1', MessageType.USER).id;
        id2 = result.current.addMessage('Message 2', MessageType.USER).id;
      });

      act(() => {
        result.current.updateMessage(id1, 'Updated 1');
      });

      const msg2 = result.current.messages.find((m) => m.id === id2);
      expect(msg2?.content).toBe('Message 2');
    });
  });

  describe('deleteMessage', () => {
    it('should delete a message', () => {
      const { result } = renderHook(() => useMessages());

      let messageId: string;
      act(() => {
        messageId = result.current.addMessage('Test', MessageType.USER).id;
      });

      act(() => {
        result.current.deleteMessage(messageId);
      });

      expect(result.current.messages.length).toBe(0);
    });

    it('should not affect other messages', () => {
      const { result } = renderHook(() => useMessages());

      let id1: string, id2: string;
      act(() => {
        id1 = result.current.addMessage('Message 1', MessageType.USER).id;
        id2 = result.current.addMessage('Message 2', MessageType.USER).id;
      });

      act(() => {
        result.current.deleteMessage(id1);
      });

      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].id).toBe(id2);
    });
  });

  describe('clearMessages', () => {
    it('should clear all messages', () => {
      const { result } = renderHook(() => useMessages());

      act(() => {
        result.current.addMessage('Message 1', MessageType.USER);
        result.current.addMessage('Message 2', MessageType.USER);
      });

      act(() => {
        result.current.clearMessages();
      });

      expect(result.current.messages.length).toBe(0);
      expect(result.current.streamingState).toBe(StreamingState.IDLE);
    });
  });

  describe('streaming', () => {
    it('should start streaming', () => {
      const { result } = renderHook(() => useMessages());

      let streamId: string;
      act(() => {
        streamId = result.current.startStreaming(MessageType.ASSISTANT);
      });

      expect(result.current.messages.length).toBe(1);
      expect(result.current.messages[0].isStreaming).toBe(true);
      expect(result.current.messages[0].content).toBe('');
      expect(result.current.streamingState).toBe(StreamingState.STREAMING);
    });

    it('should update streaming message', () => {
      const { result } = renderHook(() => useMessages());

      let streamId: string;
      act(() => {
        streamId = result.current.startStreaming(MessageType.ASSISTANT);
      });

      act(() => {
        result.current.updateStreaming(streamId, 'Partial');
      });

      expect(result.current.messages[0].content).toBe('Partial');
      expect(result.current.messages[0].isStreaming).toBe(true);
    });

    it('should complete streaming', () => {
      const { result } = renderHook(() => useMessages());

      let streamId: string;
      act(() => {
        streamId = result.current.startStreaming(MessageType.ASSISTANT);
        result.current.updateStreaming(streamId, 'Complete');
      });

      act(() => {
        result.current.completeStreaming(streamId);
      });

      expect(result.current.messages[0].isStreaming).toBe(false);
      expect(result.current.streamingState).toBe(StreamingState.COMPLETE);
    });

    it('should support multiple streaming updates', () => {
      const { result } = renderHook(() => useMessages());

      let streamId: string;
      act(() => {
        streamId = result.current.startStreaming(MessageType.ASSISTANT);
      });

      act(() => {
        result.current.updateStreaming(streamId, 'Part 1');
        result.current.updateStreaming(streamId, 'Part 1 Part 2');
        result.current.updateStreaming(streamId, 'Part 1 Part 2 Part 3');
      });

      expect(result.current.messages[0].content).toBe('Part 1 Part 2 Part 3');
    });
  });

  describe('message ordering', () => {
    it('should maintain insertion order', () => {
      const { result } = renderHook(() => useMessages());

      act(() => {
        result.current.addMessage('First', MessageType.USER);
        result.current.addMessage('Second', MessageType.ASSISTANT);
        result.current.addMessage('Third', MessageType.USER);
      });

      expect(result.current.messages[0].content).toBe('First');
      expect(result.current.messages[1].content).toBe('Second');
      expect(result.current.messages[2].content).toBe('Third');
    });
  });

  describe('timestamps', () => {
    it('should add timestamp to new messages', () => {
      const { result } = renderHook(() => useMessages());

      const before = new Date();
      act(() => {
        result.current.addMessage('Test', MessageType.USER);
      });
      const after = new Date();

      const timestamp = result.current.messages[0].timestamp;
      expect(timestamp.getTime()).toBeGreaterThanOrEqual(before.getTime());
      expect(timestamp.getTime()).toBeLessThanOrEqual(after.getTime());
    });
  });
});
