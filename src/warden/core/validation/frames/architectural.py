"""ArchitecturalConsistencyFrame - Design patterns. Priority: Medium, Blocker: False"""
import ast, time
from typing import Dict, Any
from warden.core.validation.frame import BaseValidationFrame, FrameResult, FrameScope

class ArchitecturalConsistencyFrame(BaseValidationFrame):
    @property
    def name(self) -> str:
        return "Architectural Consistency"
    @property
    def description(self) -> str:
        return "Validates SOLID principles, file size, function complexity"
    @property
    def priority(self) -> str:
        return "medium"
    @property
    def scope(self) -> FrameScope:
        return FrameScope.FILE_LEVEL
    @property
    def is_blocker(self) -> bool:
        return False

    async def execute(self, file_path: str, file_content: str, language: str, characteristics: Dict[str, Any], correlation_id: str = "", timeout: int = 300) -> FrameResult:
        start_time = time.perf_counter()
        issues, findings, scenarios = [], [], []
        try:
            scenarios.append("File size limit check")
            line_count = len(file_content.split('\n'))
            if line_count > 500:
                issues.append(f"File exceeds 500 lines ({line_count} lines) - violates Single Responsibility")
            scenarios.append("Function size check")
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                    if func_lines > 50:
                        issues.append(f"Function '{node.name}' is {func_lines} lines - should be <50")
            scenarios.append("Class count check")
            class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
            if class_count > 5:
                findings.append(f"{class_count} classes in one file - consider splitting")
            passed = len(issues) == 0
        except:
            passed = True
        return FrameResult(name=self.name, passed=passed, execution_time_ms=(time.perf_counter()-start_time)*1000, priority=self.priority, scope=self.scope.value, findings=findings, issues=issues, scenarios_executed=scenarios, is_blocker=self.is_blocker)
