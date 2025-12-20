"""
Pipeline component factory.

Creates pipeline components (FrameExecutor, etc.) from configuration.
"""
from typing import List

from warden.models.pipeline_config import PipelineConfig
from warden.core.validation.frame import BaseValidationFrame


def create_frame_executor_from_config(config: PipelineConfig):
    """
    Create FrameExecutor from YAML config.

    Loads only the frames specified in config with their settings.

    Args:
        config: Pipeline configuration

    Returns:
        FrameExecutor instance with configured frames
    """
    from warden.core.validation.executor import FrameExecutor
    from warden.core.validation.frames import (
        SecurityFrame,
        ChaosEngineeringFrame,
        FuzzTestingFrame,
        PropertyTestingFrame,
        ArchitecturalConsistencyFrame,
        StressTestingFrame,
    )

    # Map frame IDs to frame classes
    frame_map = {
        "security": SecurityFrame,
        "chaos": ChaosEngineeringFrame,
        "fuzz": FuzzTestingFrame,
        "property": PropertyTestingFrame,
        "architectural": ArchitecturalConsistencyFrame,
        "stress": StressTestingFrame,
    }

    # Get frame nodes from config
    frame_nodes = config.get_frame_nodes()

    # Create frame instances based on config
    frames: List[BaseValidationFrame] = []
    for node in frame_nodes:
        frame_id = node.data.get('frameId')
        if frame_id and frame_id in frame_map:
            frame_class = frame_map[frame_id]

            # Get config overrides
            on_fail = node.data.get('onFail', 'stop')
            override_blocker = (on_fail == 'stop')

            # Check if frame class accepts blocker override
            try:
                frame_instance = frame_class(is_blocker=override_blocker)
            except TypeError:
                # Frame doesn't support is_blocker override, use default
                frame_instance = frame_class()

            frames.append(frame_instance)

    # If no frames in config, use all frames
    if not frames:
        frames = [
            SecurityFrame(),
            ChaosEngineeringFrame(),
            FuzzTestingFrame(),
            PropertyTestingFrame(),
            ArchitecturalConsistencyFrame(),
            StressTestingFrame(),
        ]

    return FrameExecutor(frames=frames)
