# Git Commit Rules

## CRITICAL: Author Information

**NEVER use Claude as commit author:**
- ❌ NO `Co-Authored-By: Claude <noreply@anthropic.com>`
- ❌ NO Claude signatures in commits
- ✅ ONLY use the user's git config information

## Commit Message Format

```
<type>: <description>

[optional body]

🤖 Generated with Claude Code
```

**Do NOT include:**
- Co-Authored-By lines
- Claude email addresses
- Any reference to Claude in author/committer fields

**Always use:**
- User's configured git name and email
- Standard git commit workflow
- Optional emoji at the end only

## Examples

### ✅ CORRECT
```
feat: Add Firebase Analytics tracking

Implemented custom event logging for user actions

🤖 Generated with Claude Code
```

### ❌ INCORRECT
```
feat: Add Firebase Analytics tracking

🤖 Generated with Claude Code

Co-Authored-By: Claude <noreply@anthropic.com>
```

## Implementation

When creating commits:
1. Get user's git config
2. Use ONLY user info as author
3. Add commit message with optional emoji
4. Never add Co-Authored-By
