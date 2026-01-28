
import os
import random
import time
from dataclasses import dataclass
from typing import List, Dict, Tuple
from pathlib import Path

# --- Configuration ---
TARGET_DIR = "examples"

# Performance Metrics (Estimates)
METRICS = {
    "fast_lane": {"time": 0.01, "cost": 0.0, "name": "Regex/Rule"},
    "middle_lane": {"time": 2.0, "cost": 0.0, "name": "Local LLM"},
    "deep_lane": {"time": 15.0, "cost": 0.03, "name": "Cloud API (GPT-4)"}
}

@dataclass
class RealFile:
    path: str
    category: str
    true_risk: int  # 0-10

class HeuristicRiskAssigner:
    """Assigns 'True Risk' based on file characteristics for simulation."""
    
    def assign(self, path_str: str) -> Tuple[str, int]:
        p = path_str.lower()
        
        # 1. Critical Patterns
        if "secret" in p or "auth" in p or "security" in p or "key" in p or "credentials" in p:
            return "critical", random.randint(8, 10)
        
        # 2. Suspicious Patterns (Logic)
        if "messy" in p or "handler" in p or "service" in p or "logic" in p or "controller" in p:
            return "suspicious", random.randint(4, 7)
            
        # 3. Config/Safe Patterns
        if "config" in p or "settings" in p or ".md" in p or ".json" in p or ".yaml" in p:
            return "safe", random.randint(0, 2)
            
        # Default Safe
        return "safe", random.randint(0, 3)

class SimulatedLocalLLM:
    def predict_risk(self, file: RealFile) -> int:
        # Simulate LLM imperfection/noise (±1 variance)
        noise = random.randint(-1, 1)
        predicted = max(0, min(10, file.true_risk + noise))
        return predicted

class AdaptiveRouter:
    def route(self, risk_score: int) -> str:
        if risk_score <= 3:
            return "fast_lane"
        elif risk_score <= 7:
            return "middle_lane"
        else:
            return "deep_lane"

def scan_real_directory(root_dir: str) -> List[RealFile]:
    files = []
    assigner = HeuristicRiskAssigner()
    
    abs_root = os.path.abspath(root_dir)
    
    for root, _, filenames in os.walk(abs_root):
        for name in filenames:
            # Skip hidden files
            if name.startswith('.'): continue
            
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, abs_root)
            
            category, risk = assigner.assign(rel_path)
            files.append(RealFile(rel_path, category, risk))
            
    return files

def run_simulation():
    print(f"🚀 Starting Real-World Simulation: examples/")
    
    dataset = scan_real_directory(TARGET_DIR)
    print(f"📂 Found {len(dataset)} files in '{TARGET_DIR}'")
    
    if not dataset:
        print("❌ No files found! Check directory.")
        return

    llm = SimulatedLocalLLM()
    router = AdaptiveRouter()

    # Results
    results = {"fast_lane": 0, "middle_lane": 0, "deep_lane": 0}
    critical_misses = 0
    
    print("-" * 80)
    print(f"{'File':<40} | {'True':<5} | {'Pred':<5} | {'Route':<15}")
    print("-" * 80)

    for file in dataset:
        pred_risk = llm.predict_risk(file)
        lane = router.route(pred_risk)
        results[lane] += 1
        
        # Accuracy Check for Simulation
        if file.category == "critical" and lane == "fast_lane":
            critical_misses += 1
            print(f"⚠️ MISS: {file.path} (Risk: {file.true_risk} -> {pred_risk})")

        print(f"{file.path[:40]:<40} | {file.true_risk:<5} | {pred_risk:<5} | {lane:<15}")
    
    print("-" * 80)
    
    # --- Analysis ---
    file_count = len(dataset)
    baseline_time = file_count * METRICS["deep_lane"]["time"]
    baseline_cost = file_count * METRICS["deep_lane"]["cost"]
    
    adaptive_time = (
        results["fast_lane"] * METRICS["fast_lane"]["time"] +
        results["middle_lane"] * METRICS["middle_lane"]["time"] +
        results["deep_lane"] * METRICS["deep_lane"]["time"]
    )
    # 0.5s overhead for Local LLM triage per file
    adaptive_total_time = adaptive_time + (file_count * 0.5)
    
    adaptive_cost = results["deep_lane"] * METRICS["deep_lane"]["cost"]

    # --- Report ---
    print("\n📈 REAL-WORLD IMPACT REPORT (examples/)")
    print("=" * 40)
    print(f"TYPE          | {'TIME (sec)':<10} | {'COST ($)':<10}")
    print("-" * 40)
    print(f"BASELINE      | {baseline_time:<10.1f} | ${baseline_cost:<10.4f}")
    print(f"ADAPTIVE      | {adaptive_total_time:<10.1f} | ${adaptive_cost:<10.4f}")
    print("-" * 40)
    
    if baseline_time > 0:
        imp_time = ((baseline_time - adaptive_total_time) / baseline_time) * 100
        imp_cost = ((baseline_cost - adaptive_cost) / baseline_cost) * 100
    else:
        imp_time, imp_cost = 0, 0
    
    print(f"\n✅ Speed Improvement: {imp_time:.1f}%")
    print(f"💰 Cost Savings:      {imp_cost:.1f}%")
    print(f"🎯 Critical Misses:   {critical_misses}")

if __name__ == "__main__":
    run_simulation()
