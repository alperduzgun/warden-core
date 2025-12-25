/**
 * Session Manager - Save and restore chat sessions
 */

import {existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync} from 'fs';
import {join} from 'path';
import {homedir} from 'os';
import {nanoid} from 'nanoid';
import type {Issue} from '../lib/types.js';

const SESSIONS_DIR = join(homedir(), '.warden', 'sessions');

export interface SessionMessage {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  issues?: Issue[];
}

export interface Session {
  id: string;
  createdAt: number;
  updatedAt: number;
  projectPath: string;
  messages: SessionMessage[];
  metadata: {
    llmModel?: string;
    backend?: string;
    framesUsed?: string[];
  };
}

export class SessionManager {
  constructor() {
    // Ensure sessions directory exists
    if (!existsSync(SESSIONS_DIR)) {
      mkdirSync(SESSIONS_DIR, {recursive: true});
    }
  }

  /**
   * Create new session
   */
  create(projectPath: string): Session {
    const session: Session = {
      id: nanoid(),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      projectPath,
      messages: [],
      metadata: {},
    };

    this.save(session);
    return session;
  }

  /**
   * Save session to disk
   */
  save(session: Session): void {
    session.updatedAt = Date.now();
    const filePath = join(SESSIONS_DIR, `${session.id}.json`);
    writeFileSync(filePath, JSON.stringify(session, null, 2));
  }

  /**
   * Load session by ID
   */
  load(id: string): Session | null {
    const filePath = join(SESSIONS_DIR, `${id}.json`);

    if (!existsSync(filePath)) {
      return null;
    }

    try {
      const data = readFileSync(filePath, 'utf-8');
      return JSON.parse(data) as Session;
    } catch {
      return null;
    }
  }

  /**
   * List all sessions (sorted by update time, newest first)
   */
  list(): Session[] {
    const files = readdirSync(SESSIONS_DIR).filter(f => f.endsWith('.json'));

    const sessions = files
      .map(file => {
        try {
          const data = readFileSync(join(SESSIONS_DIR, file), 'utf-8');
          return JSON.parse(data) as Session;
        } catch {
          return null;
        }
      })
      .filter((s): s is Session => s !== null);

    // Sort by updated time (newest first)
    return sessions.sort((a, b) => b.updatedAt - a.updatedAt);
  }

  /**
   * Get last session
   */
  getLastSession(): Session | null {
    const sessions = this.list();
    return sessions.length > 0 ? sessions[0] || null : null;
  }

  /**
   * Delete session
   */
  delete(id: string): boolean {
    const filePath = join(SESSIONS_DIR, `${id}.json`);

    if (!existsSync(filePath)) {
      return false;
    }

    try {
      const {unlinkSync} = require('fs');
      unlinkSync(filePath);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Add message to session
   */
  addMessage(session: Session, message: SessionMessage): void {
    session.messages.push(message);
    this.save(session);
  }

  /**
   * Get sessions directory
   */
  getSessionsDir(): string {
    return SESSIONS_DIR;
  }
}

// Singleton instance
export const sessionManager = new SessionManager();
