
"""
Baseline Manager for Warden.

Handles fetching, loading, and validating the baseline artifact.
Supports vendor-agnostic fetching via configured commands.
"""

import json
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

class BaselineManager:
    """
    Manages the lifecycle of the baseline.json file.
    """

    def __init__(self, project_root: Path, config: Dict[str, Any] = None):
        self.project_root = project_root
        self.config = config or {}
        
        # Default Config
        self.baseline_config = self.config.get('baseline', {})
        self.enabled = self.baseline_config.get('enabled', False)
        
        # Resolve baseline path
        raw_path = self.baseline_config.get('path', '.warden/baseline.json')
        self.baseline_path = self.project_root / raw_path
        
        self.fetch_command = self.baseline_config.get('fetch_command')
        self.auto_fetch = self.baseline_config.get('auto_fetch', False)

    def fetch_latest_baseline(self) -> Optional[Path]:
        """
        Fetches the latest baseline using the configured command.
        Returns the path if successful, None otherwise.
        """
        if not self.fetch_command:
            logger.debug("baseline_fetch_skip_no_command")
            return None

        logger.info("baseline_fetch_start", command=self.fetch_command)
        
        try:
            # Create parent dir if needed
            self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Execute fetch command
            # Security Note: We use shell=True to allow complex user commands (pipes, etc.)
            # But the input comes from config.yaml which is trusted repo code.
            # Ideally we split, but users might want "aws s3 cp ... | jq ..."
            # For strict security we could enforce shlex.split but that breaks pipes.
            # Given config is part of repo, RCE risk is equal to malicious code in repo.
            
            subprocess.run(
                self.fetch_command,
                shell=True,
                cwd=str(self.project_root),
                check=True,
                capture_output=True,
                text=True
            )
            
            if self.baseline_path.exists():
                logger.info("baseline_fetch_success", path=str(self.baseline_path))
                return self.baseline_path
            else:
                logger.warning("baseline_fetch_completed_but_file_missing", path=str(self.baseline_path))
                return None
                
        except subprocess.CalledProcessError as e:
            logger.warning("baseline_fetch_failed", error=str(e), stderr=e.stderr)
            return None
        except Exception as e:
            logger.error("baseline_fetch_error", error=str(e))
            return None

    def load_baseline(self) -> Optional[Dict[str, Any]]:
        """
        Loads the baseline from disk.
        """
        if not self.baseline_path.exists():
            return None
            
        try:
            with open(self.baseline_path, 'r') as f:
                data = json.load(f)
                return data
        except Exception as e:
            logger.error("baseline_load_failed", error=str(e))
            return None

    def is_outdated(self, max_age_hours: int = 24) -> bool:
        """
        Checks if the local baseline is outdated based on file modification time.
        """
        if not self.baseline_path.exists():
            return True
            
        mtime = datetime.fromtimestamp(self.baseline_path.stat().st_mtime)
        age = datetime.now() - mtime
        return age > timedelta(hours=max_age_hours)

    def get_fingerprints(self) -> set[str]:
        """
        Returns a set of fingerprints for all findings in the baseline.
        Fingerprint formation: hash(rule_id + file_path + line_context_hash + message)
        
        Note: File paths in baseline are relative to project root.
        """
        data = self.load_baseline()
        if not data:
            return set()
            
        findings = []
        # Handle structured report with frameResults
        if 'frameResults' in data:
            for fr in data['frameResults']:
                findings.extend(fr.get('findings', []))
        # Handle flat list or legacy format
        elif 'findings' in data:
            findings = data['findings']
             
        fingerprints = set()
        for f in findings:
            fp = f.get('fingerprint')
            if fp:
                fingerprints.add(fp)
            else:
                # Dynamic fingerprint generation if missing in baseline
                rule = f.get('id') or f.get('rule_id') or f.get('ruleId', 'unknown')
                
                # Extract path from location "file:line" or similar
                location = f.get('location', '')
                path = f.get('file_path') or f.get('path') or f.get('file')
                if not path and location:
                    path = location.split(':')[0]
                
                path = path or 'unknown'
                msg = f.get('message', '')
                
                # Include code snippet to distinguish findings in same file
                snippet = f.get('code_snippet') or f.get('codeSnippet') or f.get('code', '')
                
                # We can't easily reproduce context hash without code, so rely on these
                composite = f"{rule}:{path}:{msg}:{snippet}"
                if composite:
                    import hashlib
                    fingerprints.add(hashlib.sha256(composite.encode()).hexdigest())
                    
        return fingerprints
