"""
Pipeline run models for Panel compatibility.

These models match the Panel TypeScript types exactly:
- PipelineRun: Main execution container with steps and summary
- Step: Individual pipeline step (5 types)
- SubStep: Validation frame substeps (6 types)
- PipelineSummary: Aggregated metrics

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal
from uuid import uuid4

from warden.shared.domain.base_model import BaseDomainModel


# Type aliases for Panel compatibility
StepType = Literal['analysis', 'classification', 'validation', 'fortification', 'cleaning']
StepStatus = Literal['pending', 'running', 'completed', 'failed', 'skipped']
SubStepType = Literal['security', 'chaos', 'fuzz', 'property', 'stress', 'architectural']
PipelineStatus = Literal['running', 'success', 'failed']
ActiveTabId = Literal['logs', 'findings', 'fortifications', 'cleanings', 'diff', 'config', 'test-results']


@dataclass
class SubStep(BaseDomainModel):
    """
    Validation frame substep.

    Panel TypeScript equivalent:
    ```typescript
    export interface SubStep {
      id: string
      name: string
      type: SubStepType
      status: StepStatus
      duration?: string
    }
    ```

    Examples:
        - security: "Security Analysis"
        - chaos: "Chaos Engineering"
        - fuzz: "Fuzz Testing"
        - property: "Property-Based Testing"
        - stress: "Stress Testing"
        - architectural: "Architectural Validation"
    """

    id: str
    name: str
    type: SubStepType
    status: StepStatus
    duration: Optional[str] = None  # e.g., "0.8s", "1.2s"

    def __post_init__(self) -> None:
        """Validate substep type."""
        valid_types: tuple = ('security', 'chaos', 'fuzz', 'property', 'stress', 'architectural')
        if self.type not in valid_types:
            raise ValueError(f"Invalid substep type: {self.type}. Must be one of {valid_types}")


@dataclass
class Step(BaseDomainModel):
    """
    Pipeline step.

    Panel TypeScript equivalent:
    ```typescript
    export interface Step {
      id: string
      name: string
      type: StepType
      status: StepStatus
      duration?: string
      score?: string
      subSteps?: SubStep[]
    }
    ```

    Five step types:
    1. analysis: Initial code assessment, produces score (e.g., "4/10")
    2. classification: Strategy determination (e.g., "5 strategies")
    3. validation: Multi-frame execution with 6 substeps
    4. fortification: Code improvements applied
    5. cleaning: Code quality improvements
    """

    id: str
    name: str
    type: StepType
    status: StepStatus
    duration: Optional[str] = None  # e.g., "0.8s", "12s"
    score: Optional[str] = None  # e.g., "4/10" (for analysis step)
    sub_steps: Optional[List[SubStep]] = None  # Only for validation step

    def __post_init__(self) -> None:
        """Validate step type and substeps."""
        valid_types: tuple = ('analysis', 'classification', 'validation', 'fortification', 'cleaning')
        if self.type not in valid_types:
            raise ValueError(f"Invalid step type: {self.type}. Must be one of {valid_types}")

        # Only validation step should have substeps
        if self.type == 'validation' and not self.sub_steps:
            # Initialize with 6 substeps if not provided
            self.sub_steps = self._create_default_substeps()
        elif self.type != 'validation' and self.sub_steps:
            raise ValueError(f"Only validation step can have substeps, got {self.type}")

    def _create_default_substeps(self) -> List[SubStep]:
        """Create default 6 substeps for validation step."""
        substep_configs = [
            ('security', 'Security Analysis'),
            ('chaos', 'Chaos Engineering'),
            ('fuzz', 'Fuzz Testing'),
            ('property', 'Property-Based Testing'),
            ('stress', 'Stress Testing'),
            ('architectural', 'Architectural Validation'),
        ]

        return [
            SubStep(
                id=f"{self.id}-{substep_type}",
                name=substep_name,
                type=substep_type,  # type: ignore
                status='pending'
            )
            for substep_type, substep_name in substep_configs
        ]

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()

        # Convert substeps if present
        if self.sub_steps:
            data['subSteps'] = [substep.to_json() for substep in self.sub_steps]

        return data


@dataclass
class PipelineSummary(BaseDomainModel):
    """
    Pipeline execution summary.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineSummary {
      score: {
        before: number
        after: number
      }
      lines: {
        before: number
        after: number
      }
      duration: string
      progress: {
        current: number
        total: number
      }
      findings: {
        critical: number
        high: number
        medium: number
        low: number
      }
      aiSource: string
    }
    ```

    Aggregated metrics for the entire pipeline run.
    """

    score_before: float  # e.g., 4.0
    score_after: float  # e.g., 8.5
    lines_before: int  # Lines of code before
    lines_after: int  # Lines after refactoring
    duration: str  # Total execution time (e.g., "1m 43s")
    progress_current: int  # Completed steps
    progress_total: int  # Total steps
    findings_critical: int
    findings_high: int
    findings_medium: int
    findings_low: int
    ai_source: str  # e.g., "Claude", "GPT-4"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON with nested objects."""
        return {
            'score': {
                'before': self.score_before,
                'after': self.score_after
            },
            'lines': {
                'before': self.lines_before,
                'after': self.lines_after
            },
            'duration': self.duration,
            'progress': {
                'current': self.progress_current,
                'total': self.progress_total
            },
            'findings': {
                'critical': self.findings_critical,
                'high': self.findings_high,
                'medium': self.findings_medium,
                'low': self.findings_low
            },
            'aiSource': self.ai_source
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'PipelineSummary':
        """Parse Panel JSON (nested structure) to Python model."""
        return cls(
            score_before=data['score']['before'],
            score_after=data['score']['after'],
            lines_before=data['lines']['before'],
            lines_after=data['lines']['after'],
            duration=data['duration'],
            progress_current=data['progress']['current'],
            progress_total=data['progress']['total'],
            findings_critical=data['findings']['critical'],
            findings_high=data['findings']['high'],
            findings_medium=data['findings']['medium'],
            findings_low=data['findings']['low'],
            ai_source=data['aiSource']
        )


@dataclass
class PipelineRun(BaseDomainModel):
    """
    Pipeline execution run.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineRun {
      id: string
      runNumber: number
      status: 'running' | 'success' | 'failed'
      trigger: string
      startTime: string
      steps: Step[]
      summary: PipelineSummary
      activeStepId?: string
      activeSubStepId?: string
      activeTabId: string
      testResults?: ValidationTestDetails
    }
    ```

    Main container for pipeline execution state and results.
    Written to `.warden/pipeline-run-{id}.json` for Panel consumption.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    run_number: int = 1
    status: PipelineStatus = 'running'
    trigger: str = "Manual execution"  # e.g., "Push to main", "Manual", "PR #123"
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    steps: List[Step] = field(default_factory=list)
    summary: Optional[PipelineSummary] = None
    active_step_id: Optional[str] = None
    active_sub_step_id: Optional[str] = None
    active_tab_id: ActiveTabId = 'logs'
    test_results: Optional[Dict[str, Any]] = None  # ValidationTestDetails - defined separately

    def __post_init__(self) -> None:
        """Initialize with default 5 steps if not provided."""
        if not self.steps:
            self.steps = self._create_default_steps()

    def _create_default_steps(self) -> List[Step]:
        """Create default 5 pipeline steps."""
        step_configs = [
            ('analysis', 'Analysis'),
            ('classification', 'Classification'),
            ('validation', 'Validation'),
            ('fortification', 'Fortification'),
            ('cleaning', 'Cleaning'),
        ]

        return [
            Step(
                id=step_type,
                name=step_name,
                type=step_type,  # type: ignore
                status='pending'
            )
            for step_type, step_name in step_configs
        ]

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()

        # Convert steps
        data['steps'] = [step.to_json() for step in self.steps]

        # Convert summary if present
        if self.summary:
            data['summary'] = self.summary.to_json()

        # Convert test results if present
        if self.test_results:
            data['testResults'] = self.test_results

        return data

    def start_step(self, step_id: str, substep_id: Optional[str] = None) -> None:
        """Mark a step (or substep) as active and running."""
        self.active_step_id = step_id
        self.active_sub_step_id = substep_id

        # Update step status
        for step in self.steps:
            if step.id == step_id:
                step.status = 'running'

                # Update substep status if provided
                if substep_id and step.sub_steps:
                    for substep in step.sub_steps:
                        if substep.id == substep_id:
                            substep.status = 'running'
                            break
                break

    def complete_step(self, step_id: str, substep_id: Optional[str] = None,
                     duration: Optional[str] = None, failed: bool = False) -> None:
        """Mark a step (or substep) as completed or failed."""
        for step in self.steps:
            if step.id == step_id:
                # Update substep if provided
                if substep_id and step.sub_steps:
                    for substep in step.sub_steps:
                        if substep.id == substep_id:
                            substep.status = 'failed' if failed else 'completed'
                            if duration:
                                substep.duration = duration
                            break
                else:
                    # Update step
                    step.status = 'failed' if failed else 'completed'
                    if duration:
                        step.duration = duration
                break

    def set_step_score(self, step_id: str, score: str) -> None:
        """Set score for a step (typically analysis step)."""
        for step in self.steps:
            if step.id == step_id:
                step.score = score
                break

    def complete_pipeline(self, success: bool = True) -> None:
        """Mark entire pipeline as completed or failed."""
        self.status = 'success' if success else 'failed'
        self.active_step_id = None
        self.active_sub_step_id = None
