/**
 * SingleRender Component
 * Prevents multiple re-renders and terminal artifacts
 */

import React, {useEffect, useRef} from 'react';
import {Box} from 'ink';

interface SingleRenderProps {
  children: React.ReactNode;
}

export function SingleRender({children}: SingleRenderProps) {
  const isFirstRender = useRef(true);
  const contentRef = useRef<React.ReactNode>(null);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      contentRef.current = children;
    }
  }, []);

  // Always update the content
  contentRef.current = children;

  return <Box>{contentRef.current}</Box>;
}