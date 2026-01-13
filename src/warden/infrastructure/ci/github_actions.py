"""
GitHub Actions template generator for Warden.

Generates GitHub Actions workflow files for running Warden in CI/CD.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class GitHubActionsConfig:
    """Configuration for GitHub Actions workflow."""

    workflow_name: str = "Warden Analysis"
    trigger_events: List[str] = None
    python_version: str = "3.11"
    warden_version: Optional[str] = None
    fail_on_issues: bool = True
    upload_artifacts: bool = True
    frames: Optional[List[str]] = None

    def __post_init__(self):
        if self.trigger_events is None:
            self.trigger_events = ["pull_request", "push"]
        if self.frames is None:
            self.frames = ["security", "fuzz", "property"]


class GitHubActionsTemplate:
    """Generates GitHub Actions workflow templates for Warden."""

    @staticmethod
    def generate(config: GitHubActionsConfig) -> str:
        """
        Generate GitHub Actions workflow YAML content.

        Args:
            config: Configuration for the workflow

        Returns:
            YAML content as string
        """
        warden_install = (
            f"pip install warden-core=={config.warden_version}"
            if config.warden_version
            else "pip install warden-core"
        )

        frames_arg = (
            " ".join(f"--frame {frame}" for frame in config.frames)
            if config.frames
            else ""
        )

        fail_arg = "--fail-on-issues" if config.fail_on_issues else ""

        trigger_section = GitHubActionsTemplate._generate_triggers(
            config.trigger_events
        )

        template = f"""name: {config.workflow_name}

{trigger_section}

jobs:
  warden-analysis:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for GitChanges frame

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '{config.python_version}'

      - name: Install Warden
        run: {warden_install}

      - name: Run Warden Analysis
        run: |
          warden analyze {frames_arg} {fail_arg} --ci --output report.json

      - name: Upload Analysis Report
        if: {str(config.upload_artifacts).lower()}
        uses: actions/upload-artifact@v4
        with:
          name: warden-report
          path: report.json
          retention-days: 30

      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = JSON.parse(fs.readFileSync('report.json', 'utf8'));

            const criticalCount = report.issues.filter(i => i.severity === 0).length;
            const highCount = report.issues.filter(i => i.severity === 1).length;

            const comment = `## Warden Analysis Report

            **Issues Found:** ${{report.issues.length}}
            - Critical: ${{criticalCount}}
            - High: ${{highCount}}

            See artifacts for full report.`;

            github.rest.issues.createComment({{
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: comment
            }});
"""

        return template

    @staticmethod
    def _generate_triggers(events: List[str]) -> str:
        """Generate trigger section for workflow."""
        if len(events) == 1:
            return f"'on': [{events[0]}]"

        trigger_lines = ["'on':"]
        for event in events:
            if event == "push":
                trigger_lines.extend(
                    [
                        "  push:",
                        "    branches:",
                        "      - main",
                        "      - dev",
                    ]
                )
            elif event == "pull_request":
                trigger_lines.extend(
                    [
                        "  pull_request:",
                        "    branches:",
                        "      - main",
                        "      - dev",
                    ]
                )
            elif event == "schedule":
                trigger_lines.extend(
                    [
                        "  schedule:",
                        "    - cron: '0 0 * * 0'  # Weekly on Sunday",
                    ]
                )
            else:
                trigger_lines.append(f"  {event}:")

        return "\n".join(trigger_lines)

    @staticmethod
    def save_to_file(config: GitHubActionsConfig, output_path: Path) -> None:
        """
        Generate and save workflow to file.

        Args:
            config: Workflow configuration
            output_path: Path to save workflow file
        """
        content = GitHubActionsTemplate.generate(config)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    @staticmethod
    def validate_workflow(workflow_path: Path) -> bool:
        """
        Validate GitHub Actions workflow file.

        Args:
            workflow_path: Path to workflow file

        Returns:
            True if valid, False otherwise
        """
        if not workflow_path.exists():
            return False

        try:
            import yaml

            content = workflow_path.read_text()
            data = yaml.safe_load(content)

            # Basic validation
            required_keys = ["name", "on", "jobs"]
            for key in required_keys:
                if key not in data:
                    return False

            # Validate jobs structure
            if not isinstance(data["jobs"], dict):
                return False

            for job_name, job_config in data["jobs"].items():
                if "runs-on" not in job_config:
                    return False
                if "steps" not in job_config:
                    return False

            return True

        except Exception:
            return False
