"""
PTZ Preset Management System.
Handles preset sweeps, idle behavior, and automatic returns.
"""
import time
import threading
from typing import List, Dict, Optional
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import config
from services.ptz_controller.onvif_client import PTZClient

logger = get_logger(__name__)


class PresetManager:
    """Manages PTZ presets and automated sweep behavior."""
    
    def __init__(self, ptz_client: PTZClient):
        """
        Initialize preset manager.
        
        Args:
            ptz_client: PTZClient instance
        """
        self.ptz = ptz_client
        self.presets: List[Dict] = []
        self.current_preset_idx = 0
        
        # Load configuration
        preset_config = config.get_section('ptz').get('presets', [])
        idle_config = config.get_section('ptz').get('idle_behavior', {})
        
        self.idle_enabled = idle_config.get('enabled', True)
        self.idle_timeout_s = idle_config.get('timeout_seconds', 30)
        self.default_preset_id = idle_config.get('return_to_preset', 1)
        self.sweep_enabled = idle_config.get('sweep_enabled', True)
        self.sweep_interval_s = idle_config.get('sweep_interval_seconds', 60)
        
        self.last_activity_time = time.time()
        self.is_idle = False
        self.sweep_thread: Optional[threading.Thread] = None
        self.running = False
        
        self._load_presets()
    
    def _load_presets(self):
        """Load presets from camera."""
        try:
            self.presets = self.ptz.get_presets()
            logger.info(
                "presets_loaded",
                count=len(self.presets),
                presets=[p['name'] for p in self.presets]
            )
        except Exception as e:
            logger.error(
                "preset_load_failed",
                error=str(e),
                exc_info=True
            )
    
    def mark_activity(self):
        """Mark that PTZ activity occurred (reset idle timer)."""
        self.last_activity_time = time.time()
        if self.is_idle:
            self.is_idle = False
            logger.info("exiting_idle_mode")
    
    def goto_preset_by_id(self, preset_id: int) -> bool:
        """
        Go to preset by ID.
        
        Args:
            preset_id: Preset ID (1-indexed)
        
        Returns:
            True if successful
        """
        try:
            # Find preset by ID
            preset = next(
                (p for p in self.presets if p['token'] == str(preset_id)),
                None
            )
            
            if not preset:
                logger.warning("preset_not_found", preset_id=preset_id)
                return False
            
            success = self.ptz.goto_preset(str(preset_id))
            if success:
                self.mark_activity()
                logger.info(
                    "moved_to_preset",
                    preset_id=preset_id,
                    name=preset.get('name')
                )
            
            return success
        
        except Exception as e:
            logger.error(
                "goto_preset_error",
                preset_id=preset_id,
                error=str(e),
                exc_info=True
            )
            return False
    
    def next_preset(self) -> bool:
        """Move to next preset in sequence."""
        if not self.presets:
            return False
        
        self.current_preset_idx = (self.current_preset_idx + 1) % len(self.presets)
        preset = self.presets[self.current_preset_idx]
        
        return self.ptz.goto_preset(preset['token'])
    
    def startup_sweep(self):
        """Perform startup sweep through all presets."""
        if not self.presets:
            logger.warning("no_presets_for_sweep")
            return
        
        logger.info("starting_sweep", preset_count=len(self.presets))
        
        for preset in self.presets:
            self.ptz.goto_preset(preset['token'])
            logger.info(
                "sweep_visiting_preset",
                preset_name=preset.get('name'),
                token=preset['token']
            )
            
            # Wait for movement to complete
            time.sleep(2.0)
    
    def start_idle_monitor(self):
        """Start idle monitoring and sweep thread."""
        if self.running:
            return
        
        self.running = True
        self.sweep_thread = threading.Thread(
            target=self._idle_monitor_loop,
            daemon=True
        )
        self.sweep_thread.start()
        logger.info("idle_monitor_started")
    
    def stop_idle_monitor(self):
        """Stop idle monitoring thread."""
        self.running = False
        if self.sweep_thread:
            self.sweep_thread.join(timeout=5.0)
        logger.info("idle_monitor_stopped")
    
    def _idle_monitor_loop(self):
        """Background thread for idle monitoring and sweep."""
        while self.running:
            try:
                current_time = time.time()
                elapsed_since_activity = current_time - self.last_activity_time
                
                # Check if idle timeout exceeded
                if self.idle_enabled and elapsed_since_activity > self.idle_timeout_s:
                    if not self.is_idle:
                        self.is_idle = True
                        logger.info("entering_idle_mode")
                        
                        # Return to default preset
                        if self.default_preset_id:
                            self.goto_preset_by_id(self.default_preset_id)
                
                # Perform sweep if enabled and idle
                if self.sweep_enabled and self.is_idle:
                    self.next_preset()
                    logger.debug("sweep_next_preset")
                    time.sleep(self.sweep_interval_s)
                else:
                    time.sleep(1.0)
            
            except Exception as e:
                logger.error(
                    "idle_monitor_error",
                    error=str(e),
                    exc_info=True
                )
                time.sleep(1.0)
