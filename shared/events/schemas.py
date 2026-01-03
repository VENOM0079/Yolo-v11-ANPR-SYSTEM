"""Event schemas for PTZ camera system using Pydantic."""
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class VehicleClass(str, Enum):
    """Vehicle classification types."""
    CAR = "car"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    UNKNOWN = "unknown"


class PTZCommand(str, Enum):
    """PTZ control commands."""
    MOVE_ABSOLUTE = "move_absolute"
    MOVE_RELATIVE = "move_relative"
    ZOOM = "zoom"
    GOTO_PRESET = "goto_preset"
    STOP = "stop"


class BoundingBox(BaseModel):
    """Bounding box coordinates (x1, y1, x2, y2)."""
    x1: float
    y1: float
    x2: float
    y2: float
    
    @property
    def center(self) -> Tuple[float, float]:
        """Calculate center point of bbox."""
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)
    
    @property
    def width(self) -> float:
        """Calculate width of bbox."""
        return self.x2 - self.x1
    
    @property
    def height(self) -> float:
        """Calculate height of bbox."""
        return self.y2 - self.y1
    
    @property
    def area(self) -> float:
        """Calculate area of bbox."""
        return self.width * self.height


class DetectionEvent(BaseModel):
    """Vehicle detection event."""
    event_id: str = Field(default_factory=lambda: f"det_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    frame_number: int
    bbox: BoundingBox
    vehicle_class: VehicleClass
    confidence: float = Field(ge=0.0, le=1.0)
    frame_width: int
    frame_height: int
    
    class Config:
        use_enum_values = True


class TrackingEvent(BaseModel):
    """Multi-object tracking event."""
    event_id: str = Field(default_factory=lambda: f"trk_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    track_id: int
    frame_number: int
    bbox: BoundingBox
    vehicle_class: VehicleClass
    confidence: float = Field(ge=0.0, le=1.0)
    velocity: Optional[Tuple[float, float]] = None  # (vx, vy) pixels/frame
    trajectory: List[Tuple[float, float]] = Field(default_factory=list)  # Last N positions
    age: int = 0  # Frames since track started
    hits: int = 0  # Number of detections
    
    class Config:
        use_enum_values = True


class PTZEvent(BaseModel):
    """PTZ camera control event."""
    event_id: str = Field(default_factory=lambda: f"ptz_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    command: PTZCommand
    pan: Optional[float] = None  # -1.0 to 1.0 or absolute value
    tilt: Optional[float] = None  # -1.0 to 1.0 or absolute value
    zoom: Optional[float] = None  # 0.0 to 1.0
    preset_id: Optional[int] = None
    target_track_id: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    
    class Config:
        use_enum_values = True


class PTZStatusEvent(BaseModel):
    """Current PTZ camera status."""
    event_id: str = Field(default_factory=lambda: f"ptz_status_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    pan: float
    tilt: float
    zoom: float
    current_preset: Optional[int] = None
    is_moving: bool = False
    
    class Config:
        use_enum_values = True


class ANPRRequest(BaseModel):
    """Request for ANPR processing."""
    request_id: str = Field(default_factory=lambda: f"anpr_req_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    track_id: int
    frame_number: int
    plate_crop_path: str  # Path to cropped plate image
    plate_bbox: BoundingBox  # Plate region within frame
    vehicle_bbox: BoundingBox  # Full vehicle bbox
    vehicle_class: VehicleClass
    
    class Config:
        use_enum_values = True


class ANPRResult(BaseModel):
    """ANPR/OCR result."""
    event_id: str = Field(default_factory=lambda: f"anpr_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: str
    track_id: int
    plate_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    plate_crop_path: str
    validated: bool = False  # Whether format validation passed
    raw_detections: List[Dict[str, Any]] = Field(default_factory=list)  # Raw OCR output
    
    class Config:
        use_enum_values = True


class SystemEvent(BaseModel):
    """System health and state events."""
    event_id: str = Field(default_factory=lambda: f"sys_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    service_name: str
    event_type: str  # health_check, error, state_change, etc.
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "info"  # info, warning, error, critical


# Event topic constants
class EventTopics:
    """Redis stream topic names."""
    DETECTIONS = "ptz.detections"
    TRACKING = "ptz.tracking"
    PTZ_COMMANDS = "ptz.commands"
    PTZ_STATUS = "ptz.status"
    ANPR_REQUESTS = "ptz.anpr.requests"
    ANPR_RESULTS = "ptz.anpr.results"
    SYSTEM_EVENTS = "ptz.system"
