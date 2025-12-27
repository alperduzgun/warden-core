#!/usr/bin/env tsx
/**
 * Direct test for Analyze component
 */

import React from 'react';
import {render} from 'ink';
import {Analyze} from './src/commands/analyze.js';

// Directly render Analyze component
const {waitUntilExit} = render(<Analyze filePath="/Users/alper/Documents/Development/Personal/warden-core/test_pipeline.py" />);

waitUntilExit().then(() => {
  console.log('\nAnalysis complete!');
  process.exit(0);
}).catch(error => {
  console.error('Error:', error);
  process.exit(1);
});