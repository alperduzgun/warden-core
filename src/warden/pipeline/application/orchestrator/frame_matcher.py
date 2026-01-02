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

    def __init__(self, frames: Optional[List[ValidationFrame]] = None, available_frames: Optional[List[ValidationFrame]] = None):
        """
        Initialize frame matcher.

        Args:
            frames: List of configured validation frames (Default fallback)
            available_frames: List of all available frames (For discovery/matching)
        """
        self.frames = frames or []
        self.available_frames = available_frames or self.frames

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

        # Search in all available frames, not just configured ones
        # Pass 1: Exact matches (ID or Name)
        for frame in self.available_frames:
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

        # Pass 2: Partial matches (only if no exact match found)
        # We want to match "security" to "security-analysis" but NOT "environmentsecurity" to "security"
        # The previous logic was too loose: (search in frame OR frame in search)
        
        # Valid partial match: search term is a substring of frame ID/Name (e.g. search "env" -> matches "environment-security")
        # Invalid partial match: frame ID is substring of search term (e.g. search "environment-security" -> matches "security")
        
        for frame in self.available_frames:
            frame_id_normalized = (
                frame.frame_id.lower()
                .replace('frame', '')
                .replace('-', '')
                .replace('_', '')
                .strip()
            )
            
            # Only match if search term is part of frame ID (e.g. user typed "env", matched "environment")
            # Do NOT match if frame ID is part of search term (e.g. user typed "environment-security", matched "security")
            if len(search_normalized) > 3 and search_normalized in frame_id_normalized:
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