# ID 39: Fix LSP Race Condition

Replace sleep(0.5) with event-based methods.

Use `textDocument/documentSymbol` requests instead of polling.
