"""
Target Prioritization Logic.
Selects which vehicle to track based on multiple criteria.
"""
import numpy as np
from typing import List, Optional, Tuple
from shapely.geometry import Point, Polygon
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import config
from services.vision_service.tracker import Track

logger = get_logger(__name__)


class TargetPrioritizer:
    """Prioritizes vehicles for PTZ tracking."""
    
    def __init__(self):
        """Initialize prioritizer with configuration."""
        priority_config = config.get_section('prioritization')
        
        self.strategy = priority_config.get('strategy', 'weighted')
        self.weights = priority_config.get('weights', {
            'proximity': 0.4,
            'roi': 0.3,
            'speed': 0.2,
            'novelty': 0.1
        })
        
        # Load ROI zones
        self.roi_zones = []
        for zone_config in priority_config.get('roi_zones', []):
            polygon_coords = zone_config.get('polygon', [])
            if polygon_coords:
                polygon = Polygon(polygon_coords)
                self.roi_zones.append({
                    'name': zone_config.get('name'),
                    'polygon': polygon,
                    'weight': zone_config.get('weight', 1.0)
                })
        
        self.min_target_size = priority_config.get('min_target_size_pixels', 100)
        self.tracked_ids = set()  # IDs already captured
        
        logger.info(
            "prioritizer_initialized",
            strategy=self.strategy,
            roi_zones=len(self.roi_zones)
        )
    
    def select_target(
        self,
        tracks: List[Track],
        frame_width: int,
        frame_height: int
    ) -> Optional[Track]:
        """
        Select highest priority track.
        
        Args:
            tracks: List of active tracks
            frame_width: Frame width in pixels
            frame_height: Frame height in pixels
        
        Returns:
            Selected track or None
        """
        if not tracks:
            return None
        
        # Filter out tracks that are too small
        valid_tracks = [
            t for t in tracks
            if t.bbox.height >= self.min_target_size
        ]
        
        if not valid_tracks:
            logger.debug("no_valid_tracks", reason="all_too_small")
            return None
        
        if self.strategy == 'proximity':
            return self._select_by_proximity(valid_tracks, frame_width, frame_height)
        elif self.strategy == 'roi':
            return self._select_by_roi(valid_tracks)
        elif self.strategy == 'weighted':
            return self._select_weighted(valid_tracks, frame_width, frame_height)
        else:
            # Default to first track
            return valid_tracks[0]
    
    def _select_by_proximity(
        self,
        tracks: List[Track],
        frame_width: int,
        frame_height: int
    ) -> Track:
        """Select track closest to frame center."""
        center_x = frame_width / 2
        center_y = frame_height / 2
        
        def distance_to_center(track: Track) -> float:
            tx, ty = track.bbox.center
            return np.sqrt((tx - center_x)**2 + (ty - center_y)**2)
        
        return min(tracks, key=distance_to_center)
    
    def _select_by_roi(self, tracks: List[Track]) -> Optional[Track]:
        """Select track in highest priority ROI."""
        best_track = None
        best_weight = 0.0
        
        for track in tracks:
            point = Point(track.bbox.center)
            
            for zone in self.roi_zones:
                if zone['polygon'].contains(point):
                    if zone['weight'] > best_weight:
                        best_weight = zone['weight']
                        best_track = track
        
        # If no tracks in ROI, return closest to center
        if best_track is None and tracks:
            best_track = tracks[0]
        
        return best_track
    
    def _select_weighted(
        self,
        tracks: List[Track],
        frame_width: int,
        frame_height: int
    ) -> Track:
        """Select track using weighted scoring."""
        scores = []
        
        center_x = frame_width / 2
        center_y = frame_height / 2
        
        for track in tracks:
            score = 0.0
            
            # Proximity score (closer = higher)
            tx, ty = track.bbox.center
            distance = np.sqrt((tx - center_x)**2 + (ty - center_y)**2)
            max_distance = np.sqrt(center_x**2 + center_y**2)
            proximity_score = 1.0 - (distance / max_distance)
            score += self.weights['proximity'] * proximity_score
            
            # ROI score
            point = Point(track.bbox.center)
            roi_score = 0.0
            for zone in self.roi_zones:
                if zone['polygon'].contains(point):
                    roi_score = zone['weight']
                    break
            score += self.weights['roi'] * roi_score
            
            # Speed score (moving = higher)
            vx, vy = track.velocity
            speed = np.sqrt(vx**2 + vy**2)
            speed_score = min(1.0, speed / 20.0)  # Normalize to 0-1
            score += self.weights['speed'] * speed_score
            
            # Novelty score (not yet tracked = higher)
            novelty_score = 0.0 if track.track_id in self.tracked_ids else 1.0
            score += self.weights['novelty'] * novelty_score
            
            scores.append((track, score))
        
        # Select highest score
        best_track, best_score = max(scores, key=lambda x: x[1])
        
        logger.debug(
            "target_selected",
            track_id=best_track.track_id,
            score=best_score
        )
        
        return best_track
    
    def mark_tracked(self, track_id: int):
        """Mark track as already captured."""
        self.tracked_ids.add(track_id)
        logger.debug("track_marked_captured", track_id=track_id)
