
import asyncio
import sys
from pathlib import Path

# Ensure warden is in python path
repo_root = Path(__file__).parent.parent.parent
sys.path.append(str(repo_root / "src"))

import structlog
from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase
from warden.validation.frames.architectural.architectural_frame import ArchitecturalConsistencyFrame
from warden.validation.domain.frame import CodeFile

# Configure basic logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

async def run_verification():
    project_root = repo_root
    
    # Optional: Clean memory to force re-learning
    # import shutil
    # memory_dir = project_root / ".warden" / "memory"
    # if memory_dir.exists(): shutil.rmtree(memory_dir)

    print(f"\n--- Running Verification on {project_root} ---")
    print("--- Step 1: Pre-Analysis (Learning Context) ---")
    
    pre_analysis = PreAnalysisPhase(project_root)
    
    # We teach Warden about its own SecretManager
    files_to_learn = [
        CodeFile(path="src/warden/secrets/application/secret_manager.py", content="", language="python"),
    ]
    
    # Execute pre-analysis to detect abstractions and save to memory/context
    result = await pre_analysis.execute(files_to_learn)
    
    context = result.project_context
    abstractions = context.service_abstractions
    
    print(f"Detected {len(abstractions)} Abstractions.")
    if "SecretManager" in abstractions:
        print("✅ SecretManager detected.")
    else:
        print("❌ SecretManager NOT detected.")

    print("\n--- Step 2: Validation (Checking Consistency) ---")
    
    # Initialize Frame
    frame = ArchitecturalConsistencyFrame()
    # Inject Context (Crucial Step)
    frame.set_project_context(context)
    
    # Analyze the violation example
    violation_file_path = Path(__file__).parent / "violation_example.py"
    with open(violation_file_path, "r") as f:
        content = f.read()
        
    code_file = CodeFile(
        path=str(violation_file_path),
        content=content,
        language="python"
    )
    
    frame_result = await frame.execute(code_file)
    
    print(f"Frame Status: {frame_result.status}")
    
    bypass_detected = False
    for finding in frame_result.findings:
        print(f"\n[Finding] {finding.message}")
        if "Use SecretManager instead of direct" in finding.message:
            bypass_detected = True
            
    if bypass_detected:
        print("\n✅ SUCCESS: Warden detected the architectural violation!")
    else:
        print("\n❌ FAILED: Violation not detected.")

if __name__ == "__main__":
    asyncio.run(run_verification())
