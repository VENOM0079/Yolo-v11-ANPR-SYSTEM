"""
Multi-Object Tracker using ByteTrack.
Maintains vehicle identities across frames.
"""
import numpy as np
from collections import deque
from typing import List, Tuple, Dict, Optional
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import get_tracking_config
from shared.events.schemas import BoundingBox, VehicleClass

logger = get_logger(__name__)


class Track:
    """Single object track with history."""
    
    def __init__(
        self,
        track_id: int,
        bbox: BoundingBox,
        vehicle_class: VehicleClass,
        confidence: float,
        max_history: int = 30
    ):
        """
        Initialize track.
        
        Args:
            track_id: Unique track identifier
            bbox: Initial bounding box
            vehicle_class: Vehicle classification
            confidence: Detection confidence
            max_history: Maximum trajectory history length
        """
        self.track_id = track_id
        self.bbox = bbox
        self.vehicle_class = vehicle_class
        self.confidence = confidence
        
        self.age = 0  # Frames since creation
        self.hits = 1  # Number of associated detections
        self.time_since_update = 0  # Frames since last update
        
        self.trajectory = deque(maxlen=max_history)
        self.trajectory.append(bbox.center)
        
        self.velocity = (0.0, 0.0)
    
    def update(self, bbox: BoundingBox, confidence: float):
        """Update track with new detection."""
        self.bbox = bbox
        self.confidence = confidence
        self.hits += 1
        self.time_since_update = 0
        
        # Update trajectory
        center = bbox.center
        self.trajectory.append(center)
        
        # Calculate velocity if we have history
        if len(self.trajectory) >= 2:
            prev_center = self.trajectory[-2]
            self.velocity = (
                center[0] - prev_center[0],
                center[1] - prev_center[1]
            )
    
    def predict(self):
        """Predict next position based on velocity."""
        self.age += 1
        self.time_since_update += 1
        
        # Apply velocity to bbox
        if self.velocity != (0.0, 0.0):
            vx, vy = self.velocity
            self.bbox = BoundingBox(
                x1=self.bbox.x1 + vx,
                y1=self.bbox.y1 + vy,
                x2=self.bbox.x2 + vx,
                y2=self.bbox.y2 + vy
            )


class VehicleTracker:
    """Multi-object tracker for vehicles."""
    
    def __init__(self):
        """Initialize tracker."""
        config = get_tracking_config()
        
        self.max_age = config.max_age
        self.min_hits = config.min_hits
        self.iou_threshold = config.iou_threshold
        
        self.tracks: Dict[int, Track] = {}
        self.next_id = 1
        
        logger.info(
            "tracker_initialized",
            max_age=self.max_age,
            min_hits=self.min_hits,
            iou_threshold=self.iou_threshold
        )
    
    @staticmethod
    def calculate_iou(bbox1: BoundingBox, bbox2: BoundingBox) -> float :
        """Calculate Intersection over Union."""
        # Calculate intersection
        x1 = max(bbox1.x1, bbox2.x1)
        y1 = max(bbox1.y1, bbox2.y1)
        x2 = min(bbox1.x2, bbox2.x2)
        y2 = min(bbox1.y2, bbox2.y2)
        
        if x2 < x1 or y2 < y1:
            return 0.0
        
        intersection = (x2 - x1) * (y2 - y1)
        
        # Calculate union
        area1 = bbox1.area
        area2 = bbox2.area
        union = area1 + area2 - intersection
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def update(
        self,
        detections: List[Tuple[BoundingBox, VehicleClass, float]]
    ) -> List[Track]:
        """
        Update tracker with new detections.
        
        Args:
            detections: List of (bbox, class, confidence) tuples
        
        Returns:
            List of active tracks
        """
        # Predict next position for all tracks
        for track in self.tracks.values():
            track.predict()
        
        # Associate detections to tracks
        if len(detections) == 0:
            # No detections, just age tracks
            matched_tracks = []
        else:
            matched_tracks = self._associate_detections(detections)
        
        # Remove dead tracks
        self._remove_dead_tracks()
        
        # Return confirmed tracks (min_hits met)
        confirmed_tracks = [
            track for track in self.tracks.values()
            if track.hits >= self.min_hits
        ]
        
        logger.debug(
            "tracker_update",
            num_detections=len(detections),
            active_tracks=len(self.tracks),
            confirmed_tracks=len(confirmed_tracks)
        )
        
        return confirmed_tracks
    
    def _associate_detections(
        self,
        detections: List[Tuple[BoundingBox, VehicleClass, float]]
    ) -> List[int]:
        """Associate detections to existing tracks."""
        matched_track_ids = []
        
        # Simple greedy matching based on IOU
        used_detections = set()
        
        for track_id, track in self.tracks.items():
            best_iou = 0.0
            best_det_idx = -1
            
            for det_idx, (bbox, vehicle_class, conf) in enumerate(detections):
                if det_idx in used_detections:
                    continue
                
                iou = self.calculate_iou(track.bbox, bbox)
                
                if iou > best_iou and iou > self.iou_threshold:
                    best_iou = iou
                    best_det_idx = det_idx
            
            if best_det_idx >= 0:
                # Match found
                bbox, vehicle_class, conf = detections[best_det_idx]
                track.update(bbox, conf)
                used_detections.add(best_det_idx)
                matched_track_ids.append(track_id)
        
        # Create new tracks for unmatched detections
        for det_idx, (bbox, vehicle_class, conf) in enumerate(detections):
            if det_idx not in used_detections:
                new_track = Track(
                    track_id=self.next_id,
                    bbox=bbox,
                    vehicle_class=vehicle_class,
                    confidence=conf
                )
                self.tracks[self.next_id] = new_track
                self.next_id += 1
                
                logger.debug(
                    "new_track_created",
                    track_id=new_track.track_id,
                    vehicle_class=vehicle_class
                )
        
        return matched_track_ids
    
    def _remove_dead_tracks(self):
        """Remove tracks that haven't been updated."""
        dead_track_ids = []
        
        for track_id, track in self.tracks.items():
            if track.time_since_update > self.max_age:
                dead_track_ids.append(track_id)
        
        for track_id in dead_track_ids:
            logger.debug(
                "track_removed",
                track_id=track_id,
                age=self.tracks[track_id].age,
                hits=self.tracks[track_id].hits
            )
            del self.tracks[track_id]
    
    def get_track(self, track_id: int) -> Optional[Track]:
        """Get track by ID."""
        return self.tracks.get(track_id)
    
    def get_all_tracks(self) -> List[Track]:
        """Get all active tracks."""
        return list(self.tracks.values())
