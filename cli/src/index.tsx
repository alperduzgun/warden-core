#!/usr/bin/env node
import React from 'react';
import { render } from 'ink';
import { config as loadEnv } from 'dotenv';
import { App } from './App.js';

/**
 * Warden CLI Entry Point
 *
 * Initializes the interactive CLI interface
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
    console.error('Uncaught Exception:', error);
    unmount();
    process.exit(1);
  });

  process.on('unhandledRejection', (reason: unknown) => {
    console.error('Unhandled Rejection:', reason);
    unmount();
    process.exit(1);
  });
};

/**
 * Main entry point
 */
const main = () => {
  try {
    // Render the app
    const { unmount, waitUntilExit } = render(<App />);

    // Setup handlers
    setupSignalHandlers(unmount);
    setupErrorHandlers(unmount);

    // Wait for exit
    void waitUntilExit();
  } catch (error) {
    console.error('Failed to start Warden CLI:', error);
    process.exit(1);
  }
};

// Start the application
main();
