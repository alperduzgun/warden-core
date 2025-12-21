# Warden PR Review Feature - Analysis & Implementation Plan

**Date:** 2025-12-21
**Status:** ❌ NOT IMPLEMENTED (Neither Panel nor Core)

---

## 🔍 Current State Analysis

### Panel Features (Existing)
✅ **Git Provider Integration:**
- GitHub/GitLab/Bitbucket connection management
- Repository import
- Branch selection
- Project cloning

❌ **PR Review Features (MISSING):**
- Pull Request listing
- PR diff viewing
- Inline comments
- Review status tracking
- Automated PR analysis
- Comment posting

### Core Features (Existing)
✅ **Code Analysis:**
- File-level validation
- Security, Chaos, Fuzz, Property testing
- Finding generation
- Quality scoring

❌ **PR/Git Integration (MISSING):**
- Git diff analysis
- Changed files only validation
- PR comment generation
- GitHub/GitLab API integration

---

## 🎯 PR Review Feature Requirements

### User Story
```
As a developer,
I want Warden to automatically review my Pull Requests,
So that I can catch issues before merging to main.
```

### Use Cases

#### 1. **Automatic PR Analysis (CodeRabbit-style)**
```
1. Developer opens PR on GitHub
2. GitHub webhook → Warden Backend
3. Warden analyzes changed files only
4. Warden posts review comments on PR
5. Developer sees inline comments on code
```

#### 2. **Manual PR Review (Panel UI)**
```
1. Developer opens Warden Panel
2. Selects project → "Pull Requests" tab
3. Sees list of open PRs
4. Clicks PR → sees Warden analysis
5. Can re-run analysis or approve/reject
```

#### 3. **CI/CD Integration**
```
1. PR opened → GitHub Action triggers
2. warden validate --pr <pr-number>
3. Warden analyzes PR diff
4. Posts results as PR check
5. Blocks merge if critical issues found
```

---

## 📋 Required Features

### Core (Backend) Features

#### 1. **Git Integration Module**
```python
# src/warden/git/github_client.py

class GitHubClient:
    """GitHub API client for PR operations"""

    def get_pull_request(self, repo: str, pr_number: int) -> PullRequest:
        """Fetch PR details"""

    def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """Get unified diff of PR changes"""

    def get_changed_files(self, repo: str, pr_number: int) -> List[ChangedFile]:
        """Get list of changed files with line ranges"""

    def post_review_comment(self, repo: str, pr_number: int, comment: PRComment):
        """Post inline comment on PR"""

    def create_review(self, repo: str, pr_number: int, review: PRReview):
        """Create PR review (approve/request changes/comment)"""

    def update_check_run(self, repo: str, pr_number: int, status: CheckStatus):
        """Update GitHub check status"""
```

#### 2. **PR Analysis Module**
```python
# src/warden/pr_review/analyzer.py

class PRAnalyzer:
    """Analyze PR changes for issues"""

    def analyze_pr(self, pr: PullRequest) -> PRAnalysisResult:
        """
        Main PR analysis workflow:
        1. Get changed files
        2. Extract changed line ranges
        3. Run validation on changed lines only
        4. Map findings to PR lines
        5. Generate review comments
        """

    def filter_findings_by_diff(
        self,
        findings: List[Finding],
        diff: GitDiff
    ) -> List[Finding]:
        """Only show findings on changed lines"""

    def generate_pr_comments(
        self,
        findings: List[Finding]
    ) -> List[PRComment]:
        """Convert findings to inline PR comments"""
```

#### 3. **Models**
```python
# src/warden/pr_review/domain/models.py

@dataclass
class PullRequest:
    number: int
    title: str
    author: str
    branch: str
    base_branch: str
    status: str  # 'open' | 'closed' | 'merged'
    url: str
    created_at: datetime
    updated_at: datetime
    diff_url: str

@dataclass
class ChangedFile:
    path: str
    status: str  # 'added' | 'modified' | 'deleted'
    additions: int
    deletions: int
    changed_lines: List[Tuple[int, int]]  # [(start, end), ...]

@dataclass
class PRComment:
    file_path: str
    line: int
    body: str  # Comment text (Markdown)
    severity: str  # 'critical' | 'high' | 'medium' | 'low'

@dataclass
class PRReview:
    event: str  # 'APPROVE' | 'REQUEST_CHANGES' | 'COMMENT'
    body: str  # Overall review summary
    comments: List[PRComment]

@dataclass
class PRAnalysisResult:
    pr_number: int
    status: str  # 'passed' | 'failed' | 'warning'
    total_findings: int
    critical_findings: int
    review: PRReview
    quality_score_before: float
    quality_score_after: float
```

### Panel (Frontend) Features

#### 1. **PR List View**
```typescript
// src/lib/types/pull-request.ts

export interface PullRequest {
    number: number;
    title: string;
    author: string;
    branch: string;
    baseBranch: string;
    status: 'open' | 'closed' | 'merged';
    url: string;
    createdAt: Date;
    updatedAt: Date;

    // Warden-specific
    analysisStatus: 'pending' | 'analyzing' | 'completed' | 'failed';
    wardenScore: number;  // 0-100
    findings: {
        critical: number;
        high: number;
        medium: number;
        low: number;
    };
}

export interface PRListFilters {
    status: ('open' | 'closed' | 'merged')[];
    author?: string;
    branch?: string;
    hasIssues?: boolean;  // Only show PRs with Warden findings
}
```

#### 2. **PR Detail View**
```svelte
<!-- src/routes/projects/[projectId]/pull-requests/[prNumber]/+page.svelte -->

<script>
    // PR header: Title, author, status, branches
    // Warden analysis summary
    // Changed files list
    // Inline diff with Warden comments
    // Re-run analysis button
</script>

<PRHeader pr={data.pullRequest} />
<WardenAnalysisSummary result={data.analysisResult} />
<FilesChanged files={data.changedFiles} />
<DiffViewer diff={data.diff} comments={data.wardenComments} />
```

#### 3. **Routes**
```
/projects/[projectId]/pull-requests          → PR list
/projects/[projectId]/pull-requests/[number] → PR detail with analysis
```

---

## 🏗️ Architecture Comparison

### CodeRabbit Model (GitHub App)
```
┌──────────┐    webhook    ┌──────────────┐    API    ┌─────────┐
│ GitHub   │──────────────>│ CodeRabbit   │<─────────>│ OpenAI  │
│ PR #123  │               │ Backend      │           └─────────┘
└──────────┘               └──────────────┘
                                  │
                                  │ GitHub API (post comments)
                                  ▼
                           ┌──────────────┐
                           │ GitHub PR    │
                           │ (Comments)   │
                           └──────────────┘
```

### Warden Model (Recommended)
```
┌──────────┐               ┌──────────────┐           ┌─────────┐
│ GitHub   │               │ Warden Core  │           │ Panel   │
│ PR #123  │               │ (CLI/Server) │           │ (UI)    │
└──────────┘               └──────────────┘           └─────────┘
     │                            ▲  │                      ▲
     │ webhook (optional)         │  │                      │
     └────────────────────────────┘  │                      │
                                     │ WebSocket/IPC        │
                                     └──────────────────────┘

Flow:
1. GitHub webhook → Warden Server
2. Warden analyzes PR diff
3. Warden posts comments via GitHub API
4. Panel shows analysis via WebSocket (real-time)
```

---

## 🚀 Implementation Plan

### Phase 1: Core PR Analysis (Week 1)
**Goal:** CLI can analyze PR locally

```bash
# Install Warden
pip install warden-cli

# Analyze current branch vs main
warden pr analyze

# Analyze specific PR
warden pr analyze --pr 123

# Output
✅ PR #123 Analysis Complete
📊 Quality Score: 85/100
🔍 Findings: 3 critical, 5 high, 8 medium
📝 Review: src/warden/pr_review/analysis_result.md
```

**Tasks:**
- [ ] Git diff parser
- [ ] Changed lines extractor
- [ ] Filter findings by changed lines
- [ ] Generate PR review markdown
- [ ] CLI command: `warden pr analyze`

**Deliverable:** CLI can analyze local PR changes

---

### Phase 2: GitHub API Integration (Week 2)
**Goal:** Post comments to GitHub PR

```bash
# Analyze and post to GitHub
warden pr analyze --pr 123 --post-comments

# GitHub PR shows inline comments:
# "🔒 Security: SQL injection vulnerability (Warden)"
```

**Tasks:**
- [ ] GitHub API client (PyGithub or custom)
- [ ] OAuth/PAT authentication
- [ ] Post inline comments
- [ ] Create review summary
- [ ] Update check status

**Deliverable:** Warden posts comments to GitHub PR

---

### Phase 3: Panel PR UI (Week 3)
**Goal:** Panel shows PR list and analysis

```
Panel Features:
- Projects → Pull Requests tab
- List of open/closed PRs
- Warden analysis status per PR
- Click PR → See diff + findings
- Re-run analysis button
```

**Tasks:**
- [ ] PR list page (`/projects/[id]/pull-requests`)
- [ ] PR detail page (`/projects/[id]/pull-requests/[number]`)
- [ ] Diff viewer component
- [ ] Inline comments UI
- [ ] Re-run analysis trigger

**Deliverable:** Panel shows PR analysis results

---

### Phase 4: Webhook Integration (Week 4)
**Goal:** Automatic PR analysis on GitHub events

```
GitHub → Webhook → Warden Server → Analyzes → Posts Comments
```

**Tasks:**
- [ ] FastAPI webhook endpoint
- [ ] GitHub webhook verification
- [ ] Event handling (PR opened, synchronized)
- [ ] Background job queue (Celery/RQ)
- [ ] Ngrok/tunnel for dev testing

**Deliverable:** Fully automated PR review bot

---

## 📊 Feature Comparison

| Feature | CodeRabbit | Cursor | Warden (Proposed) |
|---------|------------|--------|-------------------|
| **PR Analysis** | ✅ Full | ❌ No | 🔨 Planned |
| **Inline Comments** | ✅ Yes | ❌ No | 🔨 Planned |
| **GitHub Integration** | ✅ App | ❌ No | 🔨 API |
| **Local Analysis** | ❌ No | ✅ Yes | ✅ Yes (CLI) |
| **Web UI** | ✅ Yes | ❌ No | 🔨 Planned |
| **Auto Review** | ✅ Webhook | ❌ No | 🔨 Planned |
| **Multi-provider** | ✅ GH/GL | ❌ No | 🔨 Planned (GH/GL/BB) |

---

## 🎯 MVP (Minimum Viable Product)

**Target: 2 Weeks**

### Core MVP
```bash
# Install
pip install warden-cli

# Analyze current PR
cd my-repo
git checkout feature-branch
warden pr analyze --base main

# Output: Markdown report with findings
```

**Features:**
1. ✅ Git diff parser
2. ✅ Changed lines detector
3. ✅ Run validation on changed files
4. ✅ Filter findings to changed lines only
5. ✅ Generate markdown review

**No GitHub API, no posting, just local analysis.**

### Panel MVP
```
/projects/[id]/pull-requests → Coming Soon page
```

**Defer to Phase 3.**

---

## 🔧 Technical Implementation Details

### 1. Git Diff Parsing

```python
# src/warden/git/diff_parser.py

import git
from typing import List, Dict

class DiffParser:
    """Parse git diff to extract changed lines"""

    def parse_diff(self, repo_path: str, base: str, head: str) -> Dict[str, List[Tuple[int, int]]]:
        """
        Returns:
            {
                "src/file.py": [(10, 15), (23, 30)],  # Changed line ranges
                "src/other.py": [(5, 8)]
            }
        """
        repo = git.Repo(repo_path)
        diff = repo.git.diff(f"{base}...{head}", unified=0)

        changed_lines = {}
        current_file = None

        for line in diff.split('\n'):
            if line.startswith('+++'):
                current_file = line[6:]  # Remove '+++ b/'
                changed_lines[current_file] = []
            elif line.startswith('@@'):
                # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                parts = line.split('@@')[1].strip().split()
                new_range = parts[1][1:]  # Remove '+'
                if ',' in new_range:
                    start, count = map(int, new_range.split(','))
                else:
                    start, count = int(new_range), 1
                changed_lines[current_file].append((start, start + count - 1))

        return changed_lines
```

### 2. Filter Findings by Changed Lines

```python
# src/warden/pr_review/filter.py

def filter_findings_by_diff(
    findings: List[Finding],
    changed_lines: Dict[str, List[Tuple[int, int]]]
) -> List[Finding]:
    """Only keep findings on changed lines"""

    filtered = []

    for finding in findings:
        file_path = finding.location.split(':')[0]
        line_number = int(finding.location.split(':')[1])

        if file_path not in changed_lines:
            continue

        # Check if line is in any changed range
        for start, end in changed_lines[file_path]:
            if start <= line_number <= end:
                filtered.append(finding)
                break

    return filtered
```

### 3. Generate PR Review Comment

```python
# src/warden/pr_review/comment_generator.py

def generate_review_comment(finding: Finding) -> PRComment:
    """Convert Finding to PR comment"""

    severity_emoji = {
        'critical': '🔴',
        'high': '🟠',
        'medium': '🟡',
        'low': '🔵'
    }

    body = f"""
{severity_emoji[finding.severity]} **{finding.severity.upper()}**: {finding.message}

**Location:** `{finding.location}`

{finding.detail or ''}

```python
{finding.code or ''}
```

---
🤖 Generated by Warden
"""

    file_path, line = finding.location.split(':')

    return PRComment(
        file_path=file_path,
        line=int(line),
        body=body.strip(),
        severity=finding.severity
    )
```

---

## ⚠️ Challenges & Considerations

### 1. **False Positives**
- Changed lines might trigger issues that were already there
- Solution: Compare with baseline (previous commit analysis)

### 2. **GitHub API Rate Limits**
- 5000 requests/hour for authenticated
- Solution: Batch comments, use GraphQL API

### 3. **Large PRs**
- 1000+ changed files
- Solution: Sample files, priority-based analysis

### 4. **Private Repos**
- Need secure token storage
- Solution: Encrypted credentials, vault integration

### 5. **Multi-provider Support**
- GitHub, GitLab, Bitbucket different APIs
- Solution: Provider abstraction layer (already exists in Panel!)

---

## 💡 Recommendations

### Short Term (Now)
1. ✅ **Start with CLI MVP**
   - `warden pr analyze` command
   - Local git diff analysis
   - Markdown report output

2. ✅ **Panel: Add "Coming Soon" page**
   - `/projects/[id]/pull-requests` route
   - "PR Review feature coming soon" message

### Medium Term (Next Month)
3. 🔨 **GitHub API integration**
   - Post comments to PRs
   - Manual trigger from CLI

4. 🔨 **Panel UI**
   - PR list view
   - Analysis results display

### Long Term (Future)
5. 🔮 **Webhook automation**
   - GitHub App
   - Auto-review on PR events

6. 🔮 **Advanced features**
   - AI-powered review summaries
   - Suggested fixes
   - Approval workflows

---

## 📝 Summary

### Current Status
- ❌ **Panel:** NO PR review features
- ❌ **Core:** NO PR/Git integration
- ✅ **Infrastructure:** Git provider connections exist (can build on this)

### Recommendation
**Start with CLI MVP:**
```bash
cd warden-core
warden pr analyze --base main --head feature-branch
```

**Output:**
```markdown
# Warden PR Analysis

**Branch:** feature-branch → main
**Changed Files:** 12
**Quality Score:** 78/100

## 🔴 Critical Issues (2)
- [src/auth.py:45] SQL injection vulnerability
- [src/api.py:89] Hardcoded API key

## 🟠 High Issues (5)
...

## Summary
❌ **NOT READY TO MERGE**
Critical issues must be fixed before merging.
```

This gives immediate value without complex GitHub integration!

---

**Next Steps:**
1. Approve this plan
2. Start Phase 1 (CLI MVP)
3. Create GitHub issue for tracking

**Ready to start implementation?**
