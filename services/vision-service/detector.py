"""
YOLOv11 Vehicle Detector.
Performs inference on frames to detect vehicles.
"""
import torch
import numpy as np
from ultralytics import YOLO
from typing import List, Tuple
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import get_detection_config
from shared.events.schemas import BoundingBox, VehicleClass

logger = get_logger(__name__)


class VehicleDetector:
    """YOLOv11 vehicle detection engine."""
    
    # COCO class IDs for vehicles
    VEHICLE_CLASSES = {
        2: VehicleClass.CAR,
        3: VehicleClass.CAR,  # 'car' in COCO
        5: VehicleClass.BUS,
        7: VehicleClass.TRUCK,
        3: VehicleClass.MOTORCYCLE
    }
    
    def __init__(self, model_path: str = None):
        """
        Initialize YOLOv11 detector.
        
        Args:
            model_path: Path to YOLO model weights
        """
        config = get_detection_config()
        
        self.model_path = model_path or config.model_path
        self.confidence_threshold = config.confidence_threshold
        self.iou_threshold = config.iou_threshold
        self.device = config.device
        self.half_precision = config.half_precision
        
        logger.info(
            "loading_yolo_model",
            model_path=self.model_path,
            device=self.device
        )
        
        # Load YOLO model
        self.model = YOLO(self.model_path)
        
        # Move to device
        if self.device != 'cpu':
            self.model.to(f'cuda:{self.device}')
        
        # Convert to half precision if enabled
        if self.half_precision and self.device != 'cpu':
            self.model.model.half()
        
        logger.info(
            "yolo_model_loaded",
            device=self.device,
            half_precision=self.half_precision
        )
    
    def detect(
        self,
        frame: np.ndarray
    ) -> List[Tuple[BoundingBox, VehicleClass, float]]:
        """
        Detect vehicles in frame.
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of (BoundingBox, VehicleClass, confidence) tuples
        """
        try:
            # Run inference
            results = self.model.predict(
                frame,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                classes=list(self.VEHICLE_CLASSES.keys()),
                verbose=False,
                device=self.device
            )
            
            detections = []
            
            if len(results) > 0:
                result = results[0]
                boxes = result.boxes
                
                for box in boxes:
                    # Extract bounding box coordinates
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    
                    # Get class and confidence
                    class_id = int(box.cls[0].cpu().item())
                    confidence = float(box.conf[0].cpu().item())
                    
                    # Map to vehicle class
                    vehicle_class = self.VEHICLE_CLASSES.get(
                        class_id,
                        VehicleClass.UNKNOWN
                    )
                    
                    # Create bounding box
                    bbox = BoundingBox(
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2)
                    )
                    
                    detections.append((bbox, vehicle_class, confidence))
            
            logger.debug(
                "detection_complete",
                num_detections=len(detections)
            )
            
            return detections
        
        except Exception as e:
            logger.error(
                "detection_failed",
                error=str(e),
                exc_info=True
            )
            return []
    
    def detect_batch(
        self,
        frames: List[np.ndarray]
    ) -> List[List[Tuple[BoundingBox, VehicleClass, float]]]:
        """
        Detect vehicles in batch of frames.
        
        Args:
            frames: List of input frames
        
        Returns:
            List of detection lists (one per frame)
        """
        return [self.detect(frame) for frame in frames]
