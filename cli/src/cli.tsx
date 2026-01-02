#!/usr/bin/env node

/**
 * Warden CLI Entry Point
 * Modern, minimal CLI for Warden code analysis
 */

import React from 'react';
import {render} from 'ink';
import meow from 'meow';
import {Scan} from './commands/scan.js';
import {Status} from './commands/status.js';
import {Analyze} from './commands/analyze.js';
import {Chat} from './commands/chat.js';
import {Frames} from './commands/frames.js';

const cli = meow(
  `
  Usage
    $ warden <command> [options]

  Commands
    scan <path>         Scan directory or file for security issues
    analyze <file>      Analyze a file with all validation frames
    status              Check Warden backend status
    frames              Show available validation frames
    help                Show this help message

  Options
    --frames, -f        Specific validation frames to run (comma-separated)
    --verbose           Enable verbose logging for debugging
    --version, -v       Show version number
    --help, -h          Show this help message

  Examples
    $ warden scan src/
    $ warden scan file.py
    $ warden scan file.py --verbose
    $ warden analyze src/app.py
    $ warden analyze main.py --frames security,orphan
    $ warden status
    $ warden frames
`,
  {
    importMeta: import.meta,
    flags: {
      frames: {
        type: 'string',
        shortFlag: 'f',
      },
      verbose: {
        type: 'boolean',
        default: false,
      },
    },
  },
);

const [command, ...args] = cli.input;

// Main CLI router
async function main() {
  switch (command) {
    case 'start':
    case 'analyze': {
      const filePath = args[0];
      if (!filePath) {
        console.error(`Error: File path required for ${command} command`);
        console.log(`Usage: warden ${command} <file>`);
        process.exit(1);
      }
      render(<Analyze filePath={filePath} />);
      break;
    }

    case 'scan': {
      const path = args[0];
      if (!path) {
        console.error('Error: Path required for scan command');
        console.log('Usage: warden scan <path>');
        process.exit(1);
      }
      const frames = cli.flags.frames?.split(',');
      const verbose = cli.flags.verbose;
      render(<Scan path={path} frames={frames} verbose={verbose} />);
      break;
    }

    case 'status':
      render(<Status />);
      break;

    case 'frames':
      // Check if running in TTY mode
      if (!process.stdout.isTTY) {
        console.error('Error: frames command requires an interactive terminal (TTY)');
        console.error('Try running directly in a terminal, not through a pipe or non-interactive environment');
        process.exit(1);
      }
      render(<Frames />);
      break;

    case 'chat':
      render(<Chat />);
      break;

    case 'help':
      cli.showHelp(0);
      break;

    default:
      // Default to chat mode
      render(<Chat />);
  }
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
