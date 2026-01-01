"""
Frame matcher module for validation frames.

Handles frame matching and discovery logic.
"""

from typing import Optional, List
from warden.validation.domain.frame import ValidationFrame
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class FrameMatcher:
    """Handles frame matching and discovery."""

    def __init__(self, frames: Optional[List[ValidationFrame]] = None):
        """
        Initialize frame matcher.

        Args:
            frames: List of available validation frames
        """
        self.frames = frames or []

    def find_frame_by_name(self, name: str) -> Optional[ValidationFrame]:
        """
        Find a frame by various name formats.

        Handles formats like:
        - "security" -> SecurityFrame
        - "Security" -> SecurityFrame
        - "security-frame" -> SecurityFrame
        - "security_frame" -> SecurityFrame
        - "Security Analysis" -> SecurityFrame (by frame.name)

        Args:
            name: Frame name to search for

        Returns:
            Matching ValidationFrame or None
        """
        # Normalize the search name
        search_normalized = (
            name.lower()
            .replace('frame', '')
            .replace('-', '')
            .replace('_', '')
            .strip()
        )

        for frame in self.frames:
            # Try matching by frame_id
            frame_id_normalized = (
                frame.frame_id.lower()
                .replace('frame', '')
                .replace('-', '')
                .replace('_', '')
                .strip()
            )
            if frame_id_normalized == search_normalized:
                return frame

            # Try matching by frame name
            if hasattr(frame, 'name'):
                frame_name_normalized = (
                    frame.name.lower()
                    .replace(' ', '')
                    .replace('-', '')
                    .replace('_', '')
                    .replace('frame', '')
                    .replace('analysis', '')
                    .strip()
                )
                if frame_name_normalized == search_normalized:
                    return frame

            # Try partial matching
            if (search_normalized in frame_id_normalized or
                frame_id_normalized in search_normalized):
                return frame

        return None

    def get_frames_to_execute(
        self,
        selected_frames: Optional[List[str]] = None,
    ) -> List[ValidationFrame]:
        """
        Get frames to execute with matching and fallback logic.

        Args:
            selected_frames: List of selected frame names (from Classification)

        Returns:
            List of frames to execute
        """
        # If specific frames are selected, try to match them
        if selected_frames:
            logger.info(
                "using_classification_selected_frames",
                selected=selected_frames
            )

            # Improved frame matching logic
            frames_to_execute = []
            for selected_name in selected_frames:
                frame = self.find_frame_by_name(selected_name)
                if frame:
                    frames_to_execute.append(frame)
                    logger.debug(
                        f"Matched frame: {selected_name} -> {frame.frame_id}"
                    )
                else:
                    logger.warning(f"Could not match frame: {selected_name}")

            # If we matched at least one frame, use them
            if frames_to_execute:
                logger.info(
                    f"Executing {len(frames_to_execute)} frames from Classification"
                )
                return frames_to_execute

            # If no frames matched, fall back to all frames
            logger.warning(
                "classification_frames_not_matched_using_all_frames",
                selected=selected_frames,
                available=[f.frame_id for f in self.frames]
            )
        else:
            logger.info("no_classification_results_using_all_frames")

        # Fallback: Use all configured frames
        logger.info(f"Using all {len(self.frames)} configured frames")
        return self.frames