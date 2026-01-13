from typing import Dict, Any, List
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)

class YAMLMerger:
    """Helper to merge valid Warden YAML configuration files."""

    @staticmethod
    def merge_directory(dir_path: Path) -> Dict[str, Any]:
        """
        Load and merge all .yaml/.yml files in a directory.
        
        Merges sections:
        - project (update)
        - rules (extend)
        - global_rules (extend)
        - frame_rules (deep merge of lists)
        - ai_validation (update)
        - exclude (merge lists)
        
        Args:
            dir_path: Directory containing YAML files
            
        Returns:
            Merged configuration dictionary
        """
        merged_data: Dict[str, Any] = {
            "project": {},
            "rules": [],
            "global_rules": [],
            "frame_rules": {},
            "ai_validation": {},
            "exclude": {}
        }
        
        if not dir_path.exists() or not dir_path.is_dir():
            return merged_data

        # Files to process
        yaml_files = sorted(list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml")))
        
        for file_path in yaml_files:
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                
                YAMLMerger._merge_single_file(merged_data, data)
                
            except Exception as e:
                logger.warning(f"Failed to load rule file {file_path}: {e}")
                # We continue to try other files - resilience
                
        return merged_data

    @staticmethod
    def _merge_single_file(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Merge a single source dict into the target dict in-place."""
        # 1. Project info (last one wins)
        if "project" in source:
            target["project"].update(source["project"])
        
        # 2. Rules (append)
        if "rules" in source and isinstance(source["rules"], list):
            target["rules"].extend(source["rules"])
            
        # 3. Global rules (append)
        if "global_rules" in source and isinstance(source["global_rules"], list):
            target["global_rules"].extend(source["global_rules"])
            
        # 4. Frame rules (merge dicts)
        if "frame_rules" in source and isinstance(source["frame_rules"], dict):
            for frame_id, rules in source["frame_rules"].items():
                if frame_id not in target["frame_rules"]:
                    target["frame_rules"][frame_id] = rules
                else:
                    # Merge pre/post rules
                    existing = target["frame_rules"][frame_id]
                    if isinstance(existing, dict) and isinstance(rules, dict):
                        existing.setdefault("pre_rules", []).extend(rules.get("pre_rules", []))
                        existing.setdefault("post_rules", []).extend(rules.get("post_rules", []))
                        if "on_fail" in rules:
                            existing["on_fail"] = rules["on_fail"]
        
        # 5. AI Validation (update)
        if "ai_validation" in source:
            target["ai_validation"].update(source["ai_validation"])
            
        # 6. Exclude (merge lists)
        if "exclude" in source:
            existing_ex = target["exclude"]
            new_ex = source["exclude"]
            if "paths" in new_ex:
                existing_ex.setdefault("paths", []).extend(new_ex["paths"])
            if "files" in new_ex:
                existing_ex.setdefault("files", []).extend(new_ex["files"])
