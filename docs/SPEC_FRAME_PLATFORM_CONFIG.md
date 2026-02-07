# SpecFrame Platform Configuration Validation

## Overview

The SpecFrame now includes comprehensive validation for platform configurations, providing clear error messages and graceful error handling when configurations are invalid.

## Configuration Requirements

### Required Fields

All platform configurations must include these required fields:

```yaml
platforms:
  - name: "mobile"       # Required: Platform identifier
    path: "../my-app"    # Required: Path to platform codebase
    type: "flutter"      # Required: Platform type (must be valid enum)
    role: "consumer"     # Required: Platform role (must be valid enum)
```

### Valid Platform Types

The `type` field must be one of:

**Mobile/Frontend:**
- `universal` - AI-powered extraction (any language/SDK)
- `flutter` - Flutter/Dart
- `react` - React
- `react-native` - React Native
- `angular` - Angular
- `vue` - Vue.js
- `swift` - Swift (iOS)
- `kotlin` - Kotlin (Android)

**Backend:**
- `spring` - Spring Framework
- `spring-boot` - Spring Boot
- `nestjs` - NestJS
- `express` - Express.js
- `fastapi` - FastAPI
- `django` - Django
- `dotnet` - .NET
- `aspnetcore` - ASP.NET Core
- `go` - Go (generic)
- `gin` - Gin (Go framework)
- `echo` - Echo (Go framework)

### Valid Platform Roles

The `role` field must be one of:

- `consumer` - Frontend/Mobile app (expects API)
- `provider` - Backend service (provides API)
- `both` - Acts as both (e.g., BFF - Backend for Frontend)

## Validation Rules

### 1. Required Field Validation

**Missing `name`:**
```yaml
platforms:
  - path: "../my-app"
    type: "flutter"
    role: "consumer"
```

**Error:**
```
Platform 'name' is required. Example: name: 'mobile'
```

**Missing `path`:**
```yaml
platforms:
  - name: "mobile"
    type: "flutter"
    role: "consumer"
```

**Error:**
```
Platform 'path' is required for platform 'mobile'. Example: path: '../my-app'
```

### 2. Enum Validation

**Invalid platform type:**
```yaml
platforms:
  - name: "mobile"
    path: "../my-app"
    type: "react-js"  # Invalid - should be "react"
    role: "consumer"
```

**Error:**
```
Invalid platform type 'react-js' for platform 'mobile'.
Valid options: universal, flutter, react, react-native, angular, vue, swift, kotlin, spring, spring-boot, nestjs, express, fastapi, django, dotnet, aspnetcore, go, gin, echo
```

**Invalid role:**
```yaml
platforms:
  - name: "mobile"
    path: "../my-app"
    type: "flutter"
    role: "client"  # Invalid - should be "consumer"
```

**Error:**
```
Invalid platform role 'client' for platform 'mobile'.
Valid options: consumer, provider, both
```

### 3. Whitespace Handling

Leading and trailing whitespace is automatically trimmed:

```yaml
platforms:
  - name: "  mobile  "
    path: "  ../my-app  "
    type: "  flutter  "
    role: "  consumer  "
```

This is equivalent to:
```yaml
platforms:
  - name: "mobile"
    path: "../my-app"
    type: "flutter"
    role: "consumer"
```

## Error Handling

### Graceful Degradation

Invalid platforms are **skipped** rather than causing the entire frame to fail:

```yaml
platforms:
  - name: "mobile"
    path: "../my-app"
    type: "flutter"
    role: "consumer"

  - name: "invalid"
    path: "../api"
    type: "INVALID_TYPE"  # Invalid
    role: "provider"

  - name: "backend"
    path: "../api"
    type: "spring"
    role: "provider"
```

**Result:**
- ✅ `mobile` platform parsed successfully
- ❌ `invalid` platform skipped (logged as error)
- ✅ `backend` platform parsed successfully

**Logs:**
```
[ERROR] platform_config_validation_error
    platform=invalid
    config={'name': 'invalid', 'path': '../api', 'type': 'INVALID_TYPE', 'role': 'provider'}
    error="Invalid platform type 'INVALID_TYPE' for platform 'invalid'. Valid options: ..."

[DEBUG] platform_config_parsed platform=mobile type=flutter role=consumer
[DEBUG] platform_config_parsed platform=backend type=spring role=provider
```

### Error Logging

Validation errors are logged with:
- Platform name
- Full configuration that failed
- Clear error message with valid options

**Validation Error (ValueError):**
```
[ERROR] platform_config_validation_error
    platform=mobile
    config={'name': 'mobile', ...}
    error="Invalid platform type 'react-js' for platform 'mobile'. Valid options: ..."
```

**Unexpected Error:**
```
[ERROR] platform_config_parse_error
    platform=mobile
    config={'name': 'mobile', ...}
    error="..."
    error_type=KeyError
```

## Examples

### Valid Configuration

```yaml
frames_config:
  spec:
    platforms:
      - name: mobile
        path: ../invoice-mobile
        type: flutter
        role: consumer
        description: "Flutter mobile app"

      - name: backend
        path: ../invoice-api
        type: spring-boot
        role: provider
        description: "Spring Boot API"
```

### Common Mistakes

#### 1. Typo in Platform Type

❌ **Wrong:**
```yaml
platforms:
  - name: mobile
    path: ../app
    type: react-js  # Should be "react"
    role: consumer
```

✅ **Correct:**
```yaml
platforms:
  - name: mobile
    path: ../app
    type: react
    role: consumer
```

#### 2. Wrong Role Name

❌ **Wrong:**
```yaml
platforms:
  - name: backend
    path: ../api
    type: spring
    role: server  # Should be "provider"
```

✅ **Correct:**
```yaml
platforms:
  - name: backend
    path: ../api
    type: spring
    role: provider
```

#### 3. Missing Required Fields

❌ **Wrong:**
```yaml
platforms:
  - name: mobile
    type: flutter
    # Missing 'path' and 'role'
```

✅ **Correct:**
```yaml
platforms:
  - name: mobile
    path: ../mobile-app
    type: flutter
    role: consumer
```

## Debugging

### Enable Debug Logging

```yaml
advanced:
  debug: true
```

### Check Parsed Platforms

Look for these log entries:

**Success:**
```
[DEBUG] platform_config_parsed
    platform=mobile
    type=flutter
    role=consumer
```

**Validation Error:**
```
[ERROR] platform_config_validation_error
    platform=mobile
    config={...}
    error="..."
```

### Verify Configuration

Run a dry-run to check configuration:

```bash
warden scan --frames spec --dry-run
```

Review logs for platform parsing errors before the full scan runs.

## Migration Guide

### Updating Existing Configurations

If you have existing SpecFrame configurations, validate them:

1. **Check platform types:**
   ```yaml
   # Old (may be invalid)
   type: "react-js"

   # New (validated)
   type: "react"
   ```

2. **Check role names:**
   ```yaml
   # Old (may be invalid)
   role: "client"

   # New (validated)
   role: "consumer"
   ```

3. **Add missing required fields:**
   ```yaml
   platforms:
     - name: mobile      # ✅ Required
       path: ../app      # ✅ Required
       type: flutter     # ✅ Required
       role: consumer    # ✅ Required
   ```

## Validation Benefits

### 1. Early Error Detection
Catch configuration errors at initialization, not during analysis.

### 2. Clear Error Messages
Error messages include:
- What's wrong
- Which platform has the issue
- Valid options
- Examples of correct usage

### 3. Graceful Degradation
Invalid platforms are skipped, valid ones continue processing.

### 4. Better Debugging
Detailed logging helps identify and fix configuration issues quickly.

## See Also

- [SpecFrame Documentation](./SPEC_FRAME.md)
- [Platform Models](../src/warden/validation/frames/spec/models.py)
- [Configuration Guide](../README.md#configuration)
