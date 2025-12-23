#!/usr/bin/env node
import React from 'react';
import { render } from 'ink';
import { config as loadEnv } from 'dotenv';
import { App } from './App.js';
import { ensureBackend } from './utils/backendManager.js';

/**
 * Warden CLI Entry Point
 *
 * Initializes the interactive CLI interface with automatic backend management
 */

// Load environment variables
loadEnv();

/**
 * Handle process signals for graceful shutdown
 */
const setupSignalHandlers = (unmount: () => void) => {
  const handleSignal = (signal: string) => {
    console.log(`\nReceived ${signal}, shutting down gracefully...`);
    unmount();
    process.exit(0);
  };

  process.on('SIGINT', () => handleSignal('SIGINT'));
  process.on('SIGTERM', () => handleSignal('SIGTERM'));
};

/**
 * Handle uncaught errors
 */
const setupErrorHandlers = (unmount: () => void) => {
  process.on('uncaughtException', (error: Error) => {
    // Don't crash on EPIPE errors (broken pipe when backend isn't running)
    if ((error as any).code === 'EPIPE') {
      console.error('\n⚠️  Backend connection lost. Please ensure the Warden server is running.\n');
      return;
    }

    console.error('Uncaught Exception:', error);
    unmount();
    process.exit(1);
  });

  process.on('unhandledRejection', (reason: unknown) => {
    // Handle promise rejections gracefully
    if (reason instanceof Error && (reason as any).code === 'EPIPE') {
      console.error('\n⚠️  Backend connection lost. Please ensure the Warden server is running.\n');
      return;
    }

    console.error('Unhandled Rejection:', reason);
    unmount();
    process.exit(1);
  });
};

/**
 * Main entry point with automatic backend startup
 */
const main = async () => {
  try {
    // Ensure backend is running (auto-start if needed)
    await ensureBackend();

    // Render the app
    const { unmount, waitUntilExit } = render(<App />);

    // Setup handlers
    setupSignalHandlers(unmount);
    setupErrorHandlers(unmount);

    // Wait for exit
    await waitUntilExit();
  } catch (error) {
    console.error('Failed to start Warden CLI:', error);
    process.exit(1);
  }
};

// Start the application
main();
