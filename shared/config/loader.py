"""
Shared configuration management for PTZ Camera System.
Loads configuration from YAML and environment variables.
"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class ConfigLoader:
    """Central configuration loader with environment variable substitution."""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.getenv(
                "PTZ_CONFIG_PATH",
                "/app/shared/config/config.yaml"
            )
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load()
    
    def load(self):
        """Load configuration from YAML with env var substitution."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            raw_config = f.read()
        
        # Substitute environment variables
        config_text = os.path.expandvars(raw_config)
        self._config = yaml.safe_load(config_text)
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        Example: get('ptz.control.pan_speed')
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section."""
        return self._config.get(section, {})
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get full configuration dictionary."""
        return self._config


# Global configuration instance
config = ConfigLoader()


class RTSPConfig(BaseModel):
    """RTSP stream configuration."""
    primary_url: str
    backup_url: str = ""
    reconnect_delay_seconds: int = 5
    max_reconnect_attempts: int = 10
    frame_buffer_size: int = 30
    decode_threads: int = 2


class PTZConfig(BaseModel):
    """PTZ camera configuration."""
    onvif_host: str
    onvif_port: int = 80
    username: str
    password: str
    use_digest_auth: bool = True
    timeout_seconds: int = 10
    move_rate_limit_ms: int = 2000
    hysteresis_pixels: int = 50
    pan_speed: float = 0.5
    tilt_speed: float = 0.5
    zoom_step: float = 0.1
    default_preset: int = 1


class DetectionConfig(BaseModel):
    """YOLOv11 detection configuration."""
    model_path: str
    confidence_threshold: float = 0.5
    iou_threshold: float = 0.45
    device: str = "0"
    input_width: int = 640
    input_height: int = 640
    batch_size: int = 1
    half_precision: bool = True


class TrackingConfig(BaseModel):
    """Multi-object tracking configuration."""
    tracker_type: str = "bytetrack"
    max_age: int = 30
    min_hits: int = 3
    iou_threshold: float = 0.3


class ANPRConfig(BaseModel):
    """ANPR/OCR configuration."""
    engine: str = "easyocr"
    languages: str = "en"
    min_confidence: float = 0.6
    min_plate_height_pixels: int = 150
    zoom_target_plate_height: int = 200
    stability_frames: int = 5


def get_rtsp_config() -> RTSPConfig:
    """Get RTSP configuration."""
    rtsp_section = config.get_section('rtsp')
    return RTSPConfig(**rtsp_section)


def get_ptz_config() -> PTZConfig:
    """Get PTZ configuration."""
    onvif = config.get_section('ptz').get('onvif', {})
    control = config.get_section('ptz').get('control', {})
    return PTZConfig(
        onvif_host=onvif.get('host'),
        onvif_port=onvif.get('port', 80),
        username=onvif.get('username'),
        password=onvif.get('password'),
        use_digest_auth=onvif.get('use_digest_auth', True),
        timeout_seconds=onvif.get('timeout_seconds', 10),
        **control
    )


def get_detection_config() -> DetectionConfig:
    """Get detection configuration."""
    detection = config.get_section('detection')
    input_size = detection.get('input_size', {})
    return DetectionConfig(
        model_path=detection.get('model_path'),
        confidence_threshold=detection.get('confidence_threshold', 0.5),
        iou_threshold=detection.get('iou_threshold', 0.45),
        device=detection.get('device', '0'),
        input_width=input_size.get('width', 640),
        input_height=input_size.get('height', 640),
        batch_size=detection.get('batch_size', 1),
        half_precision=detection.get('half_precision', True)
    )


def get_tracking_config() -> TrackingConfig:
    """Get tracking configuration."""
    tracking = config.get_section('tracking')
    return TrackingConfig(**tracking)


def get_anpr_config() -> ANPRConfig:
    """Get ANPR configuration."""
    anpr = config.get_section('anpr')
    capture = anpr.get('capture', {})
    return ANPRConfig(
        engine=anpr.get('engine', 'easyocr'),
        languages=anpr.get('languages', 'en'),
        min_confidence=anpr.get('min_confidence', 0.6),
        min_plate_height_pixels=anpr.get('min_plate_height_pixels', 150),
        zoom_target_plate_height=capture.get('zoom_target_plate_height', 200),
        stability_frames=capture.get('stability_frames', 5)
    )
