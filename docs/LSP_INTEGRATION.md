# LSP Integration

Warden now supports integration with Language Server Protocol (LSP) servers to provide additional diagnostics alongside validation frames.

## Overview

The LSP integration allows Warden to collect diagnostics from language servers (like `pyright`, `rust-analyzer`, `gopls`, etc.) and merge them into the validation pipeline. This provides:

- **Compiler-level diagnostics** alongside security and quality checks
- **Type errors and warnings** from language servers
- **30+ language support** out of the box
- **Graceful fallback** when language servers are not available

## Configuration

LSP integration is **disabled by default** and must be explicitly enabled in your Warden configuration.

### Basic Configuration

Add to your `.warden/config.yaml`:

```yaml
pipeline:
  lsp_config:
    enabled: true
    servers: []  # Auto-detect available servers
```

### Specify Language Servers

You can explicitly configure which language servers to use:

```yaml
pipeline:
  lsp_config:
    enabled: true
    servers:
      - python
      - typescript
      - rust
      - go
```

## Supported Languages

Warden supports LSP integration for 30+ languages:

### Primary Languages
- **Python**: pyright, pylsp, jedi-language-server
- **TypeScript/JavaScript**: typescript-language-server
- **Rust**: rust-analyzer
- **Go**: gopls

### JVM Languages
- **Java**: jdtls
- **Kotlin**: kotlin-language-server
- **Scala**: metals

### .NET Languages
- **C#**: OmniSharp
- **F#**: fsautocomplete

### Web Languages
- **HTML**: vscode-html-language-server
- **CSS**: vscode-css-language-server
- **Vue**: vue-language-server

### Systems Languages
- **C/C++**: clangd, ccls
- **Zig**: zls

### Other Languages
- Ruby, PHP, Perl, Lua, Haskell, Elixir, Erlang, Clojure, Dart, Swift, and more

## Prerequisites

Language servers must be installed on your system for LSP integration to work:

### Python (pyright)
```bash
npm install -g pyright
```

### Rust (rust-analyzer)
```bash
rustup component add rust-analyzer
```

### Go (gopls)
```bash
go install golang.org/x/tools/gopls@latest
```

### TypeScript (typescript-language-server)
```bash
npm install -g typescript-language-server
```

## How It Works

1. **Discovery**: Warden automatically discovers available language servers in your PATH
2. **Initialization**: LSP clients are spawned for detected languages
3. **Document Opening**: Code files are opened in the language server
4. **Diagnostic Collection**: Warden waits for diagnostics notifications
5. **Finding Conversion**: LSP diagnostics are converted to Warden findings
6. **Merging**: LSP findings are merged with validation frame results
7. **Cleanup**: Language servers are gracefully shut down after the scan

## Pipeline Integration

LSP diagnostics are collected in **Phase 3.3** (after validation, before verification):

```
Phase 0: PRE-ANALYSIS (optional)
Phase 1: ANALYSIS (optional)
Phase 2: CLASSIFICATION (always enabled)
Phase 3: VALIDATION (frames)
Phase 3.3: LSP DIAGNOSTICS (optional, NEW!)
Phase 3.5: VERIFICATION (optional)
Phase 4: FORTIFICATION (optional)
Phase 5: CLEANING (optional)
```

## Diagnostic Mapping

LSP diagnostics are mapped to Warden findings:

| LSP Severity | Warden Severity | Description |
|--------------|----------------|-------------|
| 1 (Error)    | critical       | Type errors, syntax errors |
| 2 (Warning)  | medium         | Warnings, unused variables |
| 3 (Info)     | low            | Informational messages |
| 4 (Hint)     | low            | Hints, suggestions |

## Error Handling

LSP integration is designed to **never block the pipeline**:

- **Missing Language Server**: Gracefully skipped, no error
- **LSP Client Failure**: Logged as warning, pipeline continues
- **Timeout**: Individual language operations timeout after 30s
- **Cleanup**: LSP servers are always shut down, even on errors

## Performance Considerations

- **Startup Time**: Each language server takes ~500ms to initialize
- **Diagnostic Collection**: Adds ~500ms per file for diagnostic notification
- **Memory**: Each LSP client uses ~50-200MB RAM depending on the language
- **Recommendation**: Enable LSP only when needed (e.g., CI deep scan)

## Example: Python Project

For a Python project with `pyright` installed:

```yaml
# .warden/config.yaml
pipeline:
  lsp_config:
    enabled: true
    servers:
      - python

  # Standard validation configuration
  enable_validation: true
  enable_fortification: false
```

This will:
1. Run standard Warden validation frames (security, resilience, etc.)
2. Collect `pyright` diagnostics (type errors, undefined variables)
3. Merge findings into a single report

## Viewing LSP Findings

LSP findings are identified by:
- **Frame ID**: `lsp`
- **Message**: Prefixed with `[source]` (e.g., `[pyright]`)
- **Detail**: Contains source and code information

Example finding:
```json
{
  "id": "abc-123",
  "severity": "critical",
  "message": "[pyright] Undefined variable 'foo'",
  "location": "src/app.py:42",
  "detail": "LSP diagnostic from pyright (code: undefined-var)",
  "line": 42,
  "column": 8
}
```

## CLI Usage

### Enable LSP for a scan
```bash
# Modify config temporarily or use environment variable
WARDEN_LSP_ENABLED=true warden scan src/
```

### Check available language servers
```bash
# The LSP manager will log available servers on initialization
warden scan src/ --verbose
```

## Troubleshooting

### "No LSP findings, but language server is installed"

1. Check PATH: `which pyright`
2. Enable verbose logging: `warden scan --verbose`
3. Look for log: `lsp_binaries_discovered`

### "LSP server crashes or hangs"

- Increase timeout in code (default: 30s)
- Check server logs (usually in `/tmp`)
- Try different language server binary

### "Too many zombie processes"

- Warden automatically cleans up LSP servers
- Check logs for: `lsp_manager_shutdown_complete`
- Force cleanup: `pkill -f "pyright|rust-analyzer"`

## Limitations

- **No Server Requests**: Warden only listens to diagnostics, doesn't respond to server requests (e.g., workspace/configuration)
- **Single Root**: Each LSP client is initialized with a single project root
- **No Incremental Updates**: Files are opened fresh for each scan
- **Basic Capabilities**: Only diagnostic collection, no hover/completion/etc.

## Future Enhancements

- [ ] Configurable timeout per language
- [ ] LSP server configuration options (initializationOptions)
- [ ] Incremental document updates for faster rescans
- [ ] LSP code actions for auto-fix suggestions
- [ ] Custom LSP server binaries and arguments

## See Also

- [LSP Specification](https://microsoft.github.io/language-server-protocol/)
- [Language Server List](https://langserver.org/)
- [Warden Frame System](FRAME_SYSTEM.md)
