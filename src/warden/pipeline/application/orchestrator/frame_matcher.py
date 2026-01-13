"""
Frame matcher module for validation frames.

Handles frame matching and discovery logic.
"""

from typing import Optional, List
from pathlib import Path
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

    def is_manually_disabled(self, frame: ValidationFrame) -> bool:
        """
        Check if frame is manually disabled in config.

        Args:
            frame: ValidationFrame to check

        Returns:
            True if manually disabled, False otherwise
        """
        if not frame:
            logger.warning("is_manually_disabled_called_with_none_frame")
            return False

        if not hasattr(frame, 'frame_id') or not frame.frame_id:
            logger.warning("is_manually_disabled_frame_missing_id", frame=str(frame))
            return False

        try:
            from warden.cli_bridge.config_manager import ConfigManager

            config_mgr = ConfigManager(Path.cwd())
            enabled = config_mgr.get_frame_status(frame.frame_id)

            # None means not configured (default: enabled)
            # False means manually disabled
            is_disabled = enabled is False

            if is_disabled:
                logger.debug(
                    "frame_manually_disabled",
                    frame_id=frame.frame_id
                )

            return is_disabled

        except FileNotFoundError:
            # No config file, assume enabled
            logger.debug("config_not_found_assuming_enabled")
            return False
        except Exception as e:
            # Unexpected error, log and assume enabled (fail-safe)
            logger.error(
                "disable_check_failed",
                error=str(e),
                frame_id=frame.frame_id,
                assuming="enabled"
            )
            return False

    def is_manually_enabled(self, frame: ValidationFrame) -> bool:
        """
        Check if frame is manually enabled in config.

        User preference enforcement: If user explicitly sets enabled: true,
        the frame MUST run regardless of AI classification decision.

        Args:
            frame: ValidationFrame to check

        Returns:
            True if user explicitly set enabled: true, False otherwise
            (False means either explicit false, None, or not in config)
        """
        if not frame:
            logger.warning("is_manually_enabled_called_with_none_frame")
            return False

        if not hasattr(frame, 'frame_id') or not frame.frame_id:
            logger.warning("is_manually_enabled_frame_missing_id", frame=str(frame))
            return False

        try:
            from warden.cli_bridge.config_manager import ConfigManager

            config_mgr = ConfigManager(Path.cwd())
            enabled = config_mgr.get_frame_status(frame.frame_id)

            # True means explicit user enable (user preference)
            # False or None means not explicitly enabled
            is_enabled = enabled is True

            if is_enabled:
                logger.debug(
                    "frame_manually_enabled",
                    frame_id=frame.frame_id,
                    reason="explicit_user_preference"
                )

            return is_enabled

        except FileNotFoundError:
            # No config file, no explicit enable
            logger.debug("config_not_found_no_explicit_enable")
            return False
        except Exception as e:
            # Unexpected error, log and assume not explicitly enabled (fail-safe)
            logger.error(
                "enable_check_failed",
                error=str(e),
                frame_id=frame.frame_id,
                assuming="not_explicitly_enabled"
            )
            return False

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
                logger.debug(f"Exact match by ID: {name} -> {frame.frame_id}")
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
                    logger.debug(f"Exact match by name: {name} -> {frame.frame_id}")
                    return frame

        # Pass 2: Partial matches with word boundary check (only if no exact match found)
        # IMPORTANT: Avoid matching "security" to "demosecurity" or "environmentsecurity"
        # Only match if search term is at the START of frame ID (word boundary)

        for frame in self.available_frames:
            frame_id_normalized = (
                frame.frame_id.lower()
                .replace('frame', '')
                .replace('-', '')
                .replace('_', '')
                .strip()
            )

            # Only match if search term is at the BEGINNING of frame ID
            # Examples:
            #   "security" matches "security" ✅ (exact)
            #   "security" matches "securityanalysis" ✅ (starts with)
            #   "security" does NOT match "demosecurity" ❌ (not at start)
            #   "env" matches "environmentsecurity" ✅ (starts with)
            if len(search_normalized) > 2 and frame_id_normalized.startswith(search_normalized):
                logger.debug(f"Partial match: {name} -> {frame.frame_id} (starts with)")
                return frame

        return None

    def get_frames_to_execute(
        self,
        selected_frames: Optional[List[str]] = None,
    ) -> List[ValidationFrame]:
        """
        Get frames to execute with user preference enforcement.

        Decision Hierarchy:
        1. Hard Constraints → Language compatibility, manual disable (AI cannot override)
        2. User Preferences → Manual enable (enabled: true) - AI CANNOT skip
        3. AI Freedom → Not in config or status None - AI decides freely

        Final Selection:
        final_frames = AI_selected ∪ User_enabled - Manual_disabled

        Args:
            selected_frames: List of selected frame names (from Classification/AI)

        Returns:
            List of frames to execute (AI selection + User enforced - Disabled)
        """
        # If specific frames are selected by AI/Classification
        if selected_frames:
            logger.info(
                "using_classification_selected_frames",
                selected=selected_frames
            )

            # STEP 1: Collect AI-selected frames (with disable filtering)
            ai_frames = []
            filtered_count = 0

            for selected_name in selected_frames:
                frame = self.find_frame_by_name(selected_name)
                if frame:
                    # Check if manually disabled (hard constraint)
                    if self.is_manually_disabled(frame):
                        logger.info(
                            "skipping_manually_disabled_frame",
                            frame_id=frame.frame_id,
                            selected_by="classification",
                            reason="manual_disable_in_config"
                        )
                        filtered_count += 1
                        continue

                    ai_frames.append(frame)
                    logger.debug(
                        "ai_selected_frame",
                        frame_id=frame.frame_id,
                        source="classification"
                    )
                else:
                    logger.warning(f"Could not match frame: {selected_name}")

            # STEP 2: Collect user-enforced frames (explicit enabled: true)
            user_enabled_frames = []
            for frame in self.available_frames:
                # Skip if manually disabled (hard constraint overrides everything)
                if self.is_manually_disabled(frame):
                    continue

                # Check if user explicitly enabled this frame
                if self.is_manually_enabled(frame):
                    # Only add if NOT already in AI selection
                    if frame not in ai_frames:
                        user_enabled_frames.append(frame)
                        logger.info(
                            "user_enforced_frame",
                            frame_id=frame.frame_id,
                            reason="explicit_user_enable",
                            ai_selected=False
                        )

            # STEP 3: Merge AI selection + User preferences
            final_frames = ai_frames + user_enabled_frames

            # Log comprehensive summary
            logger.info(
                "final_frame_selection",
                ai_recommended=len(ai_frames),
                user_enforced=len(user_enabled_frames),
                total=len(final_frames),
                ai_frames=[f.frame_id for f in ai_frames],
                user_frames=[f.frame_id for f in user_enabled_frames],
                final_frames=[f.frame_id for f in final_frames]
            )

            if filtered_count > 0:
                logger.info(
                    "frames_filtered_by_disable_status",
                    total_selected=len(selected_frames),
                    after_filtering=len(final_frames),
                    filtered_count=filtered_count
                )

            # If we have at least one frame to execute, use them
            if final_frames:
                logger.info(
                    f"Executing {len(final_frames)} frames ({len(ai_frames)} AI + {len(user_enabled_frames)} User)"
                )
                return final_frames

            # If no frames matched, fall back to all frames
            logger.warning(
                "classification_frames_not_matched_using_all_frames",
                selected=selected_frames,
                available=[f.frame_id for f in self.frames]
            )
        else:
            logger.info("no_classification_results_using_all_frames")

        # Fallback: Use all configured frames, but filter disabled ones
        enabled_frames = [
            f for f in self.frames
            if not self.is_manually_disabled(f)
        ]

        disabled_count = len(self.frames) - len(enabled_frames)
        if disabled_count > 0:
            logger.info(
                "fallback_frames_filtered",
                total_configured=len(self.frames),
                enabled=len(enabled_frames),
                disabled=disabled_count
            )

        logger.info(f"Using {len(enabled_frames)} enabled configured frames")
        return enabled_frames