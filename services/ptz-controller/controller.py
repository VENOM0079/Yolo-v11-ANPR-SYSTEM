"""
PTZ Movement Controller with hysteresis and target tracking.
"""
import time
from typing import Tuple, Optional
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import config
from services.ptz_controller.onvif_client import PTZClient
from services.ptz_controller.preset_manager import PresetManager

logger = get_logger(__name__)


class PTZController:
    """
    High-level PTZ controller with hysteresis and intelligent movement.
    """
    
    def __init__(self, ptz_client: PTZClient, preset_manager: PresetManager):
        """
        Initialize PTZ controller.
        
        Args:
            ptz_client: PTZClient instance
            preset_manager: PresetManager instance
        """
        self.ptz = ptz_client
        self.preset_mgr = preset_manager
        
        # Load configuration
        control_config = config.get_section('ptz').get('control', {})
        self.hysteresis_pixels = control_config.get('hysteresis_pixels', 50)
        self.pan_speed = control_config.get('pan_speed', 0.5)
        self.tilt_speed = control_config.get('tilt_speed', 0.5)
        self.zoom_step = control_config.get('zoom_step', 0.1)
        
        self.last_target_position: Optional[Tuple[float, float]] = None
        self.current_zoom = 0.0
        
        logger.info("ptz_controller_initialized")
    
    def point_to_target(
        self,
        target_x: float,
        target_y: float,
        frame_width: int,
        frame_height: int,
        track_id: Optional[int] = None
    ) -> bool:
        """
        Point camera to target position in frame.
        
        Args:
            target_x: Target X coordinate in frame
            target_y: Target Y coordinate in frame
            frame_width: Frame width in pixels
            frame_height: Frame height in pixels
            track_id: Optional track ID for logging
        
        Returns:
            True if movement command sent
        """
        # Normalize to center-relative coordinates
        center_x = frame_width / 2
        center_y = frame_height / 2
        
        offset_x = target_x - center_x
        offset_y = target_y - center_y
        
        # Check hysteresis (dead zone)
        if self.last_target_position:
            last_x, last_y = self.last_target_position
            if (abs(target_x - last_x) < self.hysteresis_pixels and
                abs(target_y - last_y) < self.hysteresis_pixels):
                logger.debug(
                    "target_within_hysteresis",
                    track_id=track_id,
                    offset_x=offset_x,
                    offset_y=offset_y
                )
                return False
        
        # Calculate normalized pan/tilt offsets (-1 to 1)
        pan_offset = offset_x / frame_width
        tilt_offset = -offset_y / frame_height  # Invert Y for camera coords
        
        # Apply relative move
        success = self.ptz.relative_move(
            pan=pan_offset,
            tilt=tilt_offset,
            zoom=0.0,
            speed=self.pan_speed
        )
        
        if success:
            self.last_target_position = (target_x, target_y)
            self.preset_mgr.mark_activity()
            
            logger.info(
                "camera_moved_to_target",
                track_id=track_id,
                offset_x=offset_x,
                offset_y=offset_y,
                pan_offset=pan_offset,
                tilt_offset=tilt_offset
            )
        
        return success
    
    def zoom_to_target(
        self,
        target_height: float,
        desired_height: float,
        track_id: Optional[int] = None
    ) -> bool:
        """
        Zoom to achieve desired target height in frame.
        
        Args:
            target_height: Current target height in pixels
            desired_height: Desired target height in pixels
            track_id: Optional track ID for logging
        
        Returns:
            True if zoom command sent
        """
        if target_height <= 0:
            return False
        
        # Calculate zoom factor
        zoom_factor = desired_height / target_height
        
        # Determine zoom direction
        if zoom_factor > 1.2:  # Need to zoom in
            zoom_change = self.zoom_step
        elif zoom_factor < 0.8:  # Need to zoom out
            zoom_change = -self.zoom_step
        else:  # Close enough
            logger.debug(
                "zoom_adequate",
                track_id=track_id,
                current_height=target_height,
                desired_height=desired_height
            )
            return False
        
        # Calculate new zoom level
        new_zoom = max(0.0, min(1.0, self.current_zoom + zoom_change))
        
        # Apply zoom
        success = self.ptz.relative_move(
            pan=0.0,
            tilt=0.0,
            zoom=zoom_change,
            speed=0.3  # Slower zoom speed
        )
        
        if success:
            self.current_zoom = new_zoom
            self.preset_mgr.mark_activity()
            
            logger.info(
                "camera_zoomed",
                track_id=track_id,
                zoom_change=zoom_change,
                new_zoom=new_zoom,
                zoom_factor=zoom_factor
            )
        
        return success
    
    def reset_zoom(self) -> bool:
        """Reset zoom to wide view."""
        if self.current_zoom <= 0.1:
            return False
        
        # Get current status
        status = self.ptz.get_status()
        
        # Move to zero zoom
        success = self.ptz.absolute_move(
            pan=status['pan'],
            tilt=status['tilt'],
            zoom=0.0,
            speed=0.3
        )
        
        if success:
            self.current_zoom = 0.0
            logger.info("zoom_reset")
        
        return success
    
    def track_and_zoom(
        self,
        bbox_center_x: float,
        bbox_center_y: float,
        bbox_height: float,
        frame_width: int,
        frame_height: int,
        desired_bbox_height: float,
        track_id: Optional[int] = None
    ) -> Tuple[bool, bool]:
        """
        Combined tracking and zooming operation.
        
        Args:
            bbox_center_x: Bounding box center X
            bbox_center_y: Bounding box center Y
            bbox_height: Current bbox height
            frame_width: Frame width
            frame_height: Frame height
            desired_bbox_height: Desired bbox height for capture
            track_id: Track ID
        
        Returns:
            Tuple of (tracking_success, zooming_success)
        """
        # First, point to target
        tracking_success = self.point_to_target(
            bbox_center_x,
            bbox_center_y,
            frame_width,
            frame_height,
            track_id
        )
        
        # Wait a moment for movement to stabilize
        if tracking_success:
            time.sleep(0.5)
        
        # Then, zoom to desired size
        zooming_success = self.zoom_to_target(
            bbox_height,
            desired_bbox_height,
            track_id
        )
        
        return tracking_success, zooming_success
    
    def get_current_state(self) -> dict:
        """Get current PTZ state."""
        status = self.ptz.get_status()
        return {
            **status,
            'zoom_level': self.current_zoom,
            'last_target': self.last_target_position
        }
