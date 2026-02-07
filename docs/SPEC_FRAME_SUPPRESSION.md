# SpecFrame Suppression Support

## Overview

The SpecFrame now supports suppression of contract gaps through configuration rules. This allows you to suppress false positives, legacy endpoints, or gaps in third-party code that you cannot immediately fix.

## Features

### 1. Suppression Key Format

Each contract gap has a unique suppression key in the format:

```
spec:{gap_type}:{operation_name}
```

**Examples:**
- `spec:missing_operation:createUser` - Missing createUser operation
- `spec:type_mismatch:getUserById` - Type mismatch in getUserById
- `spec:nullable_mismatch:updateUser` - Nullable mismatch in updateUser
- `spec:unused:deleteUser` - Unused deleteUser operation

### 2. Suppression Rules

Suppressions are configured in `.warden/config.yaml` under `frames_config.spec.suppressions`:

```yaml
frames_config:
  spec:
    suppressions:
      # Exact match - suppress specific operation
      - rule: "spec:missing_operation:createUser"
        reason: "Legacy endpoint, being refactored"

      # Wildcard for operation - suppress all type mismatches
      - rule: "spec:type_mismatch:*"
        reason: "Type system migration in progress"

      # File pattern - suppress gaps only in specific files
      - rule: "spec:missing_operation:*"
        files: ["legacy/*.py", "vendor/*"]
        reason: "Legacy code to be refactored"

      # Suppress all spec gaps in specific files
      - rule: "spec:*:*"
        files: ["third-party/*.py"]
        reason: "Third-party code we don't control"

      # Global wildcard - suppress all spec gaps (use sparingly!)
      - rule: "*"
        files: ["tests/**/*.py"]
        reason: "Test files"
```

### 3. Wildcard Patterns

Suppressions support wildcards for flexible matching:

| Pattern | Description | Example |
|---------|-------------|---------|
| `spec:missing_operation:createUser` | Exact match | Suppresses only createUser missing operation |
| `spec:missing_operation:*` | All operations of type | Suppresses all missing operations |
| `spec:*:createUser` | All gap types for operation | Suppresses all gaps for createUser |
| `spec:*:*` | All spec gaps | Suppresses all contract gaps |
| `*` | Global wildcard | Suppresses everything (use with file patterns) |

### 4. File Pattern Matching

Use file patterns to limit suppression scope:

```yaml
suppressions:
  - rule: "spec:*:*"
    files:
      - "legacy/*.py"
      - "vendor/**/*.py"
      - "third-party/*"
    reason: "Code we don't control"
```

**Pattern syntax:**
- `*` matches any sequence of characters in a filename
- `**` matches directories recursively
- Uses fnmatch (Unix shell-style wildcards)

## Configuration Example

Complete configuration with suppressions:

```yaml
frames_config:
  spec:
    enabled: true

    platforms:
      - name: mobile
        path: ../my-app
        type: flutter
        role: consumer

      - name: backend
        path: ../my-api
        type: spring
        role: provider

    gap_analysis:
      enable_fuzzy: true
      fuzzy_threshold: 0.8

    suppressions:
      # Suppress specific legacy operations
      - rule: "spec:missing_operation:createUser"
        reason: "Legacy endpoint, being refactored in v2"

      - rule: "spec:missing_operation:updateUser"
        reason: "Legacy endpoint, being refactored in v2"

      # Suppress type mismatches during migration
      - rule: "spec:type_mismatch:*"
        files: ["src/legacy/*.py"]
        reason: "Type system migration in progress"

      # Suppress all gaps in third-party code
      - rule: "spec:*:*"
        files: ["vendor/*", "third-party/*"]
        reason: "Third-party code we don't control"
```

## Metadata Tracking

Suppressed gaps are tracked in the frame result metadata:

```json
{
  "metadata": {
    "gaps_found": 5,
    "suppressed_gaps": 3,
    "platforms_analyzed": [...]
  }
}
```

## Logging

Suppressed gaps are logged with details:

```
[INFO] gap_suppressed_by_config
    gap_type=missing_operation
    operation=createUser
    suppression_key=spec:missing_operation:createUser
```

## Best Practices

### 1. Be Specific
Prefer exact matches over wildcards when possible:

✅ **Good:**
```yaml
- rule: "spec:missing_operation:createUser"
  reason: "Legacy endpoint, scheduled for removal in Q2"
```

❌ **Avoid:**
```yaml
- rule: "spec:*:*"
  reason: "Stuff we don't want to fix"
```

### 2. Use File Patterns
Limit suppression scope with file patterns:

✅ **Good:**
```yaml
- rule: "spec:type_mismatch:*"
  files: ["legacy/*.py"]
  reason: "Legacy code during migration"
```

### 3. Document Reasons
Always provide clear reasons for suppressions:

✅ **Good:**
```yaml
- rule: "spec:missing_operation:createUser"
  reason: "Legacy endpoint, being refactored in PROJ-123"
```

❌ **Avoid:**
```yaml
- rule: "spec:missing_operation:createUser"
  reason: "Don't care"
```

### 4. Review Regularly
Periodically review suppressions to remove outdated rules:

```bash
# Check current suppressions
grep -A 5 "suppressions:" .warden/config.yaml

# Review metadata for suppressed_gaps count
warden scan --format json | jq '.metadata.suppressed_gaps'
```

## Migration Guide

If you have existing spec gaps you want to suppress:

1. **Run initial scan:**
   ```bash
   warden scan --frames spec
   ```

2. **Identify gaps to suppress:**
   Review the report and note operation names and gap types.

3. **Add suppressions:**
   ```yaml
   frames_config:
     spec:
       suppressions:
         - rule: "spec:missing_operation:createUser"
           reason: "Legacy endpoint, ticket PROJ-123"
   ```

4. **Verify suppression:**
   ```bash
   warden scan --frames spec
   # Check metadata.suppressed_gaps count
   ```

## Troubleshooting

### Suppression Not Working

1. **Check suppression key format:**
   ```
   spec:{gap_type}:{operation_name}
   ```

2. **Verify file patterns:**
   File patterns use fnmatch (Unix shell wildcards).

3. **Enable debug logging:**
   ```yaml
   advanced:
     debug: true
   ```

   Check logs for:
   ```
   [DEBUG] gap_suppressed
       gap_key=spec:missing_operation:createUser
       suppression_rule=spec:missing_operation:*
   ```

### Finding Suppression Keys

To find the suppression key for a gap:

1. Run scan without suppressions
2. Check the finding ID or logs
3. Format: `spec:{gap_type}:{operation_name}`

## See Also

- [SpecFrame Documentation](./SPEC_FRAME.md)
- [Suppression Models](../src/warden/suppression/models.py)
- [Configuration Guide](../README.md#configuration)
