"""
Configuration Handler for Warden Bridge.
Handles pipeline configuration loading and frame discovery.
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.handlers.base import BaseHandler

logger = get_logger(__name__)

class ConfigHandler(BaseHandler):
    """Handles Warden configuration, frame discovery, and consistency checks."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.active_config_name = "no-config"

    def load_pipeline_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load pipeline configuration from warden.yaml or legacy config.yaml."""
        from warden.pipeline.domain.models import PipelineConfig
        
        # Find config file
        root_manifest = self.project_root / "warden.yaml"
        legacy_config = self.project_root / ".warden" / "config.yaml"
        config_file = root_manifest if root_manifest.exists() else legacy_config

        if not config_file.exists():
            logger.warning("no_config_found", path=str(config_file))
            return {
                "config": self._get_default_pipeline_config(),
                "frames": self.get_default_frames(),
                "available_frames": self.get_available_frames(),
                "name": "default"
            }

        from warden.cli_bridge.config_manager import ConfigManager
        config_mgr = ConfigManager(self.project_root)
        
        try:
            config_data = config_mgr.read_config()
        except Exception as e:
            logger.warning("config_read_failed_falling_back", error=str(e))
            with open(config_file) as f:
                config_data = yaml.safe_load(f)

        rules_data = {}
        try:
            rules_data = config_mgr.read_rules()
        except Exception as e:
            logger.warning("rules_read_failed", error=str(e))

        # Merge rules and config
        frame_config = config_data.get('frames_config', config_data.get('frame_config', {}))
        frame_rules = rules_data.get('frame_rules', {})
        for fid, rule_cfg in frame_rules.items():
            if fid not in frame_config:
                frame_config[fid] = rule_cfg
            else:
                merged = rule_cfg.copy()
                merged.update(frame_config[fid])
                frame_config[fid] = merged

        available_frames, frame_map = self._instantiate_all_frames(frame_config)
        
        frame_names = config_data.get('frames', [])
        if not frame_names:
            frames = self.get_default_frames()
            self.active_config_name = "default"
        else:
            frames = self._select_frames(frame_names, frame_map, available_frames)
            self.active_config_name = config_data.get('name', 'project-config')

        settings = config_data.get('settings', {})
        pipeline_config = PipelineConfig(
            fail_fast=settings.get('fail_fast', True),
            timeout=settings.get('timeout', 300),
            frame_timeout=settings.get('frame_timeout', 120),
            parallel_limit=4,
            enable_pre_analysis=settings.get('enable_pre_analysis', True),
            enable_analysis=settings.get('enable_analysis', True),
            enable_classification=True,
            enable_validation=settings.get('enable_validation', True),
            enable_fortification=settings.get('enable_fortification', True),
            enable_cleaning=settings.get('enable_cleaning', True),
            pre_analysis_config=settings.get('pre_analysis_config', None),
            semantic_search_config=config_data.get('semantic_search', None),
            use_gitignore=settings.get('use_gitignore', True)
        )

        return {
            "config": pipeline_config,
            "frames": frames,
            "available_frames": available_frames,
            "name": self.active_config_name
        }

    def _get_default_pipeline_config(self):
        from warden.pipeline.domain.models import PipelineConfig
        return PipelineConfig(
            fail_fast=True,
            timeout=300,
            frame_timeout=120,
            parallel_limit=4,
            enable_pre_analysis=True,
            enable_analysis=True,
            enable_classification=True,
            enable_validation=True,
            enable_fortification=True,
            enable_cleaning=True,
        )

    def get_default_frames(self) -> List[Any]:
        from warden.validation.infrastructure.frame_registry import FrameRegistry
        registry = FrameRegistry()
        registry.discover_all()
        
        default_ids = ["security", "resilience", "architecturalconsistency", "orphan", "fuzz", "property"]
        frames = []
        for fid in default_ids:
            cls = registry.registered_frames.get(fid)
            if not cls:
                for reg_fid, c in registry.registered_frames.items():
                    if fid in reg_fid or reg_fid in fid:
                        cls = c
                        break
            if cls:
                try:
                    frames.append(cls())
                except Exception as e:
                    logger.warning("default_frame_init_failed", fid=fid, error=str(e))
        return frames

    def get_available_frames(self) -> List[Any]:
        from warden.validation.infrastructure.frame_registry import FrameRegistry
        registry = FrameRegistry()
        registry.discover_all()
        frames = []
        for fid, cls in registry.registered_frames.items():
            try:
                frames.append(cls())
            except Exception as e:
                logger.warning("frame_instantiation_failed", fid=fid, error=str(e))
        return frames

    def _instantiate_all_frames(self, frame_config: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any]]:
        from warden.validation.infrastructure.frame_registry import FrameRegistry
        registry = FrameRegistry()
        registry.discover_all()
        
        available = []
        frame_map = {}
        for fid, cls in registry.registered_frames.items():
            config = frame_config.get(fid, {})
            if not config and fid in registry.frame_metadata:
                meta = registry.frame_metadata[fid]
                if meta.id in frame_config:
                    config = frame_config[meta.id]
            try:
                instance = cls(config=config)
                available.append(instance)
                frame_map[fid] = instance
                norm_name = instance.name.replace(' ', '').replace('-', '').replace('_', '').lower()
                frame_map[norm_name] = instance
            except Exception as e:
                logger.warning("frame_init_failed", fid=fid, error=str(e))
        return available, frame_map

    def _select_frames(self, names: List[str], frame_map: Dict[str, Any], available: List[Any]) -> List[Any]:
        selected = []
        for name in names:
            norm = name.replace('-', '').replace('_', '').lower()
            if norm in frame_map:
                selected.append(frame_map[norm])
            else:
                for f in available:
                    f_norm = f.name.replace(' ', '').replace('-', '').replace('_', '').lower()
                    if f_norm == norm:
                        selected.append(f)
                        break
                else:
                    if norm == 'architectural' and 'architecturalconsistency' in frame_map:
                        selected.append(frame_map['architecturalconsistency'])
                    else:
                        logger.warning("configured_frame_not_found", name=name)
        return selected

    def validate_consistency(self) -> None:
        try:
            from warden.cli_bridge.config_manager import ConfigManager
            config_mgr = ConfigManager(self.project_root)
            result = config_mgr.validate_frame_consistency()
            if not result.get("valid"):
                for warn in result.get("warnings", []):
                    logger.warning("frame_consistency_warning", warning=warn)
            else:
                logger.info("frame_consistency_passed")
        except Exception as e:
            logger.warning("frame_consistency_check_failed", error=str(e))
