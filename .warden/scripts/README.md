# Custom Validation Scripts

This directory contains custom validation scripts that can be executed as part of Warden's rule validation pipeline.

## Script Contract

All validation scripts must follow this contract:

### Input
- **Argument 1**: Absolute path to the file being validated
- Example: `/path/to/project/src/main.py`

### Output
- **Exit Code**:
  - `0` = Validation passed (no violation)
  - `non-zero` = Validation failed (violation detected)
- **stdout**: Violation message (displayed to user if exit code is non-zero)
- **stderr**: Debug/diagnostic information (logged but not shown to user)

### Example Script

```bash
#!/bin/bash
# Example validation script

FILE="$1"

# Perform validation
if [ some_condition ]; then
    echo "Validation failed: reason for failure"
    exit 1
fi

# Validation passed
exit 0
```

### Timeout

Scripts should complete within the configured timeout (default: 30 seconds). Scripts that exceed the timeout will be killed and no violation will be reported.

## Available Scripts

### check_file_size.sh
- **Purpose**: Validates that files do not exceed 500KB
- **Exit 1 if**: File size > 500KB
- **Message**: "File too large: {size}KB (max 500KB)"

### check_complexity.sh
- **Purpose**: Validates that files are not too complex (line count)
- **Exit 1 if**: Non-blank lines > 1000
- **Message**: "File too complex: {lines} lines (max 1000)"

### check_no_todos.sh
- **Purpose**: Ensures production code has no TODO/FIXME comments
- **Exit 1 if**: Any TODO or FIXME comment found
- **Message**: "Found {count} TODO/FIXME comment(s)"

## Creating Your Own Scripts

1. Create an executable script in this directory
2. Follow the script contract (see above)
3. Add the script to your rules configuration:

```yaml
- id: "my-custom-rule"
  name: "My Custom Rule"
  category: convention
  severity: medium
  isBlocker: false
  description: "Description of what this rule validates"
  enabled: true
  type: script
  scriptPath: ".warden/scripts/my_script.sh"
  timeout: 10
  message: "Custom violation message"
  conditions: {}
```

## Security Notes

- Scripts are executed with the same permissions as Warden
- Validate all input (file paths)
- Avoid shell injection vulnerabilities
- Use absolute paths when possible
- Keep scripts simple and focused on one validation task
- Test scripts thoroughly before enabling in production

## Best Practices

1. **Keep scripts fast**: Aim for < 5 seconds execution time
2. **Provide clear messages**: Users should understand what failed and why
3. **Handle edge cases**: Check if file exists, is readable, etc.
4. **Use exit codes correctly**: 0 for pass, non-zero for fail
5. **Log to stderr**: Use stderr for debugging, stdout for violation messages
6. **Make scripts executable**: `chmod +x script.sh`
7. **Use shebang**: Start with `#!/bin/bash` or appropriate interpreter
