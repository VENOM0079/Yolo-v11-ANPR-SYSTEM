"""
Plate Region Proposer.
Estimates plate location and determines capture readiness.
"""
import numpy as np
from typing import Optional, Tuple
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import get_anpr_config
from shared.events.schemas import BoundingBox
from services.vision_service.tracker import Track

logger = get_logger(__name__)


class PlateProposer:
    """Proposes plate regions and determines capture readiness."""
    
    def __init__(self):
        """Initialize plate proposer."""
        config = get_anpr_config()
        
        self.min_plate_height = config.min_plate_height_pixels
        self.target_plate_height = config.zoom_target_plate_height
        self.stability_frames = config.stability_frames
        
        self.stable_tracks = {}  # track_id -> frame_count
        
        logger.info(
            "plate_proposer_initialized",
            min_height=self.min_plate_height,
            target_height=self.target_plate_height,
            stability_frames=self.stability_frames
        )
    
    def estimate_plate_region(
        self,
        track: Track
    ) -> Optional[BoundingBox]:
        """
        Estimate plate region within vehicle bbox.
        
        Uses heuristic: plate is in lower-front 20% of vehicle.
        
        Args:
            track: Vehicle track
        
        Returns:
            Estimated plate bounding box or None
        """
        vehicle_bbox = track.bbox
        
        # Estimate plate is in lower-front portion
        # Assuming front-facing vehicles
        plate_height = vehicle_bbox.height * 0.15  # 15% of vehicle height
        plate_width = vehicle_bbox.width * 0.6  # 60% of vehicle width
        
        # Position at bottom-center
        plate_x1 = vehicle_bbox.x1 + (vehicle_bbox.width - plate_width) / 2
        plate_y1 = vehicle_bbox.y2 - (vehicle_bbox.height * 0.25)  # Lower 25%
        plate_x2 = plate_x1 + plate_width
        plate_y2 = plate_y1 + plate_height
        
        plate_bbox = BoundingBox(
            x1=float(plate_x1),
            y1=float(plate_y1),
            x2=float(plate_x2),
            y2=float(plate_y2)
        )
        
        return plate_bbox
    
    def is_ready_for_capture(
        self,
        track: Track,
        plate_bbox: BoundingBox
    ) -> Tuple[bool, float]:
        """
        Determine if plate is ready for capture.
        
        Args:
            track: Vehicle track
            plate_bbox: Estimated plate bounding box
        
        Returns:
            Tuple of (is_ready, zoom_factor_needed)
        """
        current_height = plate_bbox.height
        
        # Check minimum height
        if current_height < self.min_plate_height:
            zoom_factor = self.target_plate_height / current_height
            return False, zoom_factor
        
        # Check stability (track has been visible for enough frames)
        track_id = track.track_id
        if track_id not in self.stable_tracks:
            self.stable_tracks[track_id] = 0
        
        self.stable_tracks[track_id] += 1
        
        if self.stable_tracks[track_id] < self.stability_frames:
            logger.debug(
                "track_not_stable",
                track_id=track_id,
                stability=self.stable_tracks[track_id],
                required=self.stability_frames
            )
            return False, 1.0
        
        # Check if target height achieved
        if current_height >= self.target_plate_height:
            logger.info(
                "plate_ready_for_capture",
                track_id=track_id,
                plate_height=current_height,
                target_height=self.target_plate_height
            )
            return True, 1.0
        
        # Need more zoom
        zoom_factor = self.target_plate_height / current_height
        return False, zoom_factor
    
    def reset_stability(self, track_id: int):
        """Reset stability counter for track."""
        if track_id in self.stable_tracks:
            del self.stable_tracks[track_id]
    
    def cleanup_old_tracks(self, active_track_ids: set):
        """Remove stability data for inactive tracks."""
        inactive_ids = set(self.stable_tracks.keys()) - active_track_ids
        for track_id in inactive_ids:
            del self.stable_tracks[track_id]
