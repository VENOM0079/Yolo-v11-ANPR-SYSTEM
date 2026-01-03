"""
ONVIF PTZ Camera Client.
Wraps ONVIF operations for pan/tilt/zoom control.
"""
import time
from typing import Optional, Tuple, Dict, Any
from onvif import ONVIFCamera
from zeep.exceptions import Fault
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import get_ptz_config

logger = get_logger(__name__)


class PTZClient:
    """ONVIF PTZ camera client with rate limiting and error handling."""
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
        use_digest: bool = True
    ):
        """
        Initialize ONVIF PTZ client.
        
        Args:
            host: Camera IP address
            port: ONVIF port (usually 80)
            username: ONVIF username
            password: ONVIF password
            use_digest: Use digest authentication
        """
        # Load from config if not provided
        if host is None:
            config = get_ptz_config()
            host = config.onvif_host
            port = config.onvif_port
            username = config.username
            password = config.password
            use_digest = config.use_digest_auth
        
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        
        self.camera: Optional[ONVIFCamera] = None
        self.ptz_service = None
        self.media_service = None
        self.profile = None
        
        self.last_move_time = 0
        self.move_rate_limit_s = 2.0  # Minimum seconds between moves
        
        self._connect()
    
    def _connect(self):
        """Establish ONVIF connection and get services."""
        try:
            logger.info("connecting_to_onvif", host=self.host, port=self.port)
            
            self.camera = ONVIFCamera(
                self.host,
                self.port,
                self.username,
                self.password,
                '/etc/onvif/wsdl/'  # Default WSDL path
            )
            
            # Get services
            self.media_service = self.camera.create_media_service()
            self.ptz_service = self.camera.create_ptz_service()
            
            # Get media profile
            profiles = self.media_service.GetProfiles()
            if not profiles:
                raise RuntimeError("No media profiles found")
            
            self.profile = profiles[0]
            logger.info(
                "onvif_connected",
                profile_token=self.profile.token
            )
        
        except Exception as e:
            logger.error(
                "onvif_connection_failed",
                host=self.host,
                error=str(e),
                exc_info=True
            )
            raise
    
    def _check_rate_limit(self) -> bool:
        """
        Check if enough time has passed since last move.
        
        Returns:
            True if move allowed, False if rate limited
        """
        current_time = time.time()
        elapsed = current_time - self.last_move_time
        
        if elapsed < self.move_rate_limit_s:
            logger.debug(
                "rate_limited",
                elapsed=elapsed,
                required=self.move_rate_limit_s
            )
            return False
        
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current PTZ position.
        
        Returns:
            Dictionary with pan, tilt, zoom values
        """
        try:
            request = self.ptz_service.create_type('GetStatus')
            request.ProfileToken = self.profile.token
            
            status = self.ptz_service.GetStatus(request)
            
            position = {
                'pan': float(status.Position.PanTilt.x),
                'tilt': float(status.Position.PanTilt.y),
                'zoom': float(status.Position.Zoom.x)
            }
            
            return position
        
        except Exception as e:
            logger.error(
                "get_status_failed",
                error=str(e),
                exc_info=True
            )
            return {'pan': 0.0, 'tilt': 0.0, 'zoom': 0.0}
    
    def absolute_move(
        self,
        pan: float,
        tilt: float,
        zoom: float,
        speed: float = 0.5
    ) -> bool:
        """
        Move to absolute pan/tilt/zoom position.
        
        Args:
            pan: Pan position (-1.0 to 1.0)
            tilt: Tilt position (-1.0 to 1.0)
            zoom: Zoom position (0.0 to 1.0)
            speed: Movement speed (0.0 to 1.0)
        
        Returns:
            True if command sent successfully
        """
        if not self._check_rate_limit():
            return False
        
        try:
            request = self.ptz_service.create_type('AbsoluteMove')
            request.ProfileToken = self.profile.token
            
            # Set destination
            request.Position = self.ptz_service.GetStatus({
                'ProfileToken': self.profile.token
            }).Position
            
            request.Position.PanTilt.x = max(-1.0, min(1.0, pan))
            request.Position.PanTilt.y = max(-1.0, min(1.0, tilt))
            request.Position.Zoom.x = max(0.0, min(1.0, zoom))
            
            # Set speed
            request.Speed = self.ptz_service.GetStatus({
                'ProfileToken': self.profile.token
            }).Position
            request.Speed.PanTilt.x = speed
            request.Speed.PanTilt.y = speed
            request.Speed.Zoom.x = speed
            
            self.ptz_service.AbsoluteMove(request)
            self.last_move_time = time.time()
            
            logger.info(
                "absolute_move",
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed=speed
            )
            
            return True
        
        except Fault as e:
            logger.error(
                "absolute_move_failed",
                error=str(e),
                exc_info=True
            )
            return False
    
    def relative_move(
        self,
        pan: float,
        tilt: float,
        zoom: float,
        speed: float = 0.5
    ) -> bool:
        """
        Move relative to current position.
        
        Args:
            pan: Pan offset (-1.0 to 1.0)
            tilt: Tilt offset (-1.0 to 1.0)
            zoom: Zoom offset (-1.0 to 1.0)
            speed: Movement speed (0.0 to 1.0)
        
        Returns:
            True if command sent successfully
        """
        if not self._check_rate_limit():
            return False
        
        try:
            request = self.ptz_service.create_type('RelativeMove')
            request.ProfileToken = self.profile.token
            
            # Set translation
            request.Translation = self.ptz_service.GetStatus({
                'ProfileToken': self.profile.token
            }).Position
            
            request.Translation.PanTilt.x = max(-1.0, min(1.0, pan))
            request.Translation.PanTilt.y = max(-1.0, min(1.0, tilt))
            request.Translation.Zoom.x = max(-1.0, min(1.0, zoom))
            
            # Set speed
            request.Speed = self.ptz_service.GetStatus({
                'ProfileToken': self.profile.token
            }).Position
            request.Speed.PanTilt.x = speed
            request.Speed.PanTilt.y = speed
            request.Speed.Zoom.x = speed
            
            self.ptz_service.RelativeMove(request)
            self.last_move_time = time.time()
            
            logger.info(
                "relative_move",
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed=speed
            )
            
            return True
        
        except Fault as e:
            logger.error(
                "relative_move_failed",
                error=str(e),
                exc_info=True
            )
            return False
    
    def continuous_move(
        self,
        pan_velocity: float,
        tilt_velocity: float,
        zoom_velocity: float
    ) -> bool:
        """
        Start continuous movement.
        
        Args:
            pan_velocity: Pan velocity (-1.0 to 1.0)
            tilt_velocity: Tilt velocity (-1.0 to 1.0)
            zoom_velocity: Zoom velocity (-1.0 to 1.0)
        
        Returns:
            True if command sent successfully
        """
        try:
            request = self.ptz_service.create_type('ContinuousMove')
            request.ProfileToken = self.profile.token
            
            request.Velocity = self.ptz_service.GetStatus({
                'ProfileToken': self.profile.token
            }).Position
            
            request.Velocity.PanTilt.x = max(-1.0, min(1.0, pan_velocity))
            request.Velocity.PanTilt.y = max(-1.0, min(1.0, tilt_velocity))
            request.Velocity.Zoom.x = max(-1.0, min(1.0, zoom_velocity))
            
            self.ptz_service.ContinuousMove(request)
            
            logger.debug(
                "continuous_move",
                pan=pan_velocity,
                tilt=tilt_velocity,
                zoom=zoom_velocity
            )
            
            return True
        
        except Fault as e:
            logger.error(
                "continuous_move_failed",
                error=str(e),
                exc_info=True
            )
            return False
    
    def stop(self) -> bool:
        """
        Stop all PTZ movement.
        
        Returns:
            True if command sent successfully
        """
        try:
            request = self.ptz_service.create_type('Stop')
            request.ProfileToken = self.profile.token
            request.PanTilt = True
            request.Zoom = True
            
            self.ptz_service.Stop(request)
            
            logger.info("ptz_stopped")
            return True
        
        except Fault as e:
            logger.error(
                "stop_failed",
                error=str(e),
                exc_info=True
            )
            return False
    
    def goto_preset(self, preset_token: str) -> bool:
        """
        Move to a saved preset.
        
        Args:
            preset_token: Preset identifier
        
        Returns:
            True if command sent successfully
        """
        if not self._check_rate_limit():
            return False
        
        try:
            request = self.ptz_service.create_type('GotoPreset')
            request.ProfileToken = self.profile.token
            request.PresetToken = str(preset_token)
            
            self.ptz_service.GotoPreset(request)
            self.last_move_time = time.time()
            
            logger.info("goto_preset", preset=preset_token)
            return True
        
        except Fault as e:
            logger.error(
                "goto_preset_failed",
                preset=preset_token,
                error=str(e),
                exc_info=True
            )
            return False
    
    def get_presets(self) -> list:
        """
        Get list of available presets.
        
        Returns:
            List of preset dictionaries
        """
        try:
            request = self.ptz_service.create_type('GetPresets')
            request.ProfileToken = self.profile.token
            
            presets = self.ptz_service.GetPresets(request)
            
            preset_list = []
            for preset in presets:
                preset_list.append({
                    'token': preset.token,
                    'name': preset.Name if hasattr(preset, 'Name') else preset.token,
                    'pan': float(preset.PTZPosition.PanTilt.x),
                    'tilt': float(preset.PTZPosition.PanTilt.y),
                    'zoom': float(preset.PTZPosition.Zoom.x)
                })
            
            return preset_list
        
        except Exception as e:
            logger.error(
                "get_presets_failed",
                error=str(e),
                exc_info=True
            )
            return []
