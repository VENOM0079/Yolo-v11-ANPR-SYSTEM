"""
Vision Service Main Entry Point.
Orchestrates detection, tracking, and PTZ control.
"""
import sys
import signal
import time
import cv2
import numpy as np
from pathlib import Path
sys.path.append('/app')

from shared.utils.logger import setup_logging, get_logger
from shared.utils.rtsp_client import RTSPClient
from shared.config.loader import config, get_rtsp_config
from shared.events.message_bus import MessageBus
from shared.events.schemas import (
    DetectionEvent, TrackingEvent, PTZEvent, ANPRRequest,
    VehicleClass, PTZCommand, EventTopics
)

from services.vision_service.detector import VehicleDetector
from services.vision_service.tracker import VehicleTracker
from services.vision_service.prioritizer import TargetPrioritizer
from services.vision_service.plate_proposer import PlateProposer

# Setup logging
logger = setup_logging("vision-service", log_level="INFO", log_format="json")

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("shutdown_signal_received")
    running = False


def save_plate_crop(frame: np.ndarray, bbox, track_id: int, frame_number: int) -> str:
    """
    Save plate crop to disk.
    
    Returns:
        Path to saved crop
    """
    crop_dir = Path("/app/data/plate_crops")
    crop_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract crop
    x1, y1, x2, y2 = int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)
    crop = frame[y1:y2, x1:x2]
    
    # Save with track_id and frame_number
    crop_path = crop_dir / f"track_{track_id}_frame_{frame_number}.jpg"
    cv2.imwrite(str(crop_path), crop)
    
    return str(crop_path)


def main():
    """Main service entry point."""
    global running
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("vision_service_starting")
    
    try:
        # Initialize components
        logger.info("initializing_detector")
        detector = VehicleDetector()
        
        logger.info("initializing_tracker")
        tracker = VehicleTracker()
        
        logger.info("initializing_prioritizer")
        prioritizer = TargetPrioritizer()
        
        logger.info("initializing_plate_proposer")
        plate_proposer = PlateProposer()
        
        # Initialize message bus
        logger.info("connecting_to_message_bus")
        redis_config = config.get_section('events').get('redis', {})
        bus = MessageBus(
            host=redis_config.get('host', 'localhost'),
            port=redis_config.get('port', 6379),
            password=redis_config.get('password'),
            stream_max_len=redis_config.get('stream_max_len', 10000)
        )
        
        # Initialize RTSP client
        logger.info("connecting_to_rtsp_stream")
        rtsp_config = get_rtsp_config()
        rtsp_client = RTSPClient(
            rtsp_url=rtsp_config.primary_url,
            backup_url=rtsp_config.backup_url,
            reconnect_delay=rtsp_config.reconnect_delay_seconds,
            max_reconnect_attempts=rtsp_config.max_reconnect_attempts,
            buffer_size=rtsp_config.frame_buffer_size
        )
        
        rtsp_client.start()
        logger.info("rtsp_stream_connected")
        
        # Main processing loop
        frame_number = 0
        current_target_id = None
        
        while running:
            try:
                # Read frame
                frame_data = rtsp_client.read(timeout=1.0)
                if frame_data is None:
                    continue
                
                frame_number, frame = frame_data
                frame_height, frame_width = frame.shape[:2]
                
                # Detect vehicles
                detections = detector.detect(frame)
                
                # Publish detection events
                for bbox, vehicle_class, confidence in detections:
                    det_event = DetectionEvent(
                        frame_number=frame_number,
                        bbox=bbox,
                        vehicle_class=vehicle_class,
                        confidence=confidence,
                        frame_width=frame_width,
                        frame_height=frame_height
                    )
                    bus.publish(EventTopics.DETECTIONS, det_event)
                
                # Update tracker
                tracks = tracker.update(detections)
                
                # Cleanup old plate proposer tracking
                active_track_ids = {t.track_id for t in tracks}
                plate_proposer.cleanup_old_tracks(active_track_ids)
                
                # Publish tracking events
                for track in tracks:
                    trk_event = TrackingEvent(
                        track_id=track.track_id,
                        frame_number=frame_number,
                        bbox=track.bbox,
                        vehicle_class=track.vehicle_class,
                        confidence=track.confidence,
                        velocity=track.velocity,
                        trajectory=list(track.trajectory),
                        age=track.age,
                        hits=track.hits
                    )
                    bus.publish(EventTopics.TRACKING, trk_event)
                
                # Select priority target
                target = prioritizer.select_target(tracks, frame_width, frame_height)
                
                if target:
                    # New target or target changed
                    if current_target_id != target.track_id:
                        logger.info(
                            "target_changed",
                            old_target=current_target_id,
                            new_target=target.track_id
                        )
                        current_target_id = target.track_id
                        plate_proposer.reset_stability(target.track_id)
                    
                    # Get plate region estimate
                    plate_bbox = plate_proposer.estimate_plate_region(target)
                    
                    # Check if ready for capture
                    ready, zoom_factor = plate_proposer.is_ready_for_capture(
                        target,
                        plate_bbox
                    )
                    
                    if ready:
                        # Save plate crop
                        crop_path = save_plate_crop(
                            frame,
                            plate_bbox,
                            target.track_id,
                            frame_number
                        )
                        
                        # Send ANPR request
                        anpr_req = ANPRRequest(
                            track_id=target.track_id,
                            frame_number=frame_number,
                            plate_crop_path=crop_path,
                            plate_bbox=plate_bbox,
                            vehicle_bbox=target.bbox,
                            vehicle_class=target.vehicle_class
                        )
                        bus.publish(EventTopics.ANPR_REQUESTS, anpr_req)
                        
                        # Mark as tracked
                        prioritizer.mark_tracked(target.track_id)
                        
                        logger.info(
                            "anpr_request_sent",
                            track_id=target.track_id,
                            crop_path=crop_path
                        )
                    else:
                        # Need to adjust PTZ
                        # Send PTZ command to point and zoom
                        target_x, target_y = target.bbox.center
                        
                        ptz_event = PTZEvent(
                            command=PTZCommand.MOVE_RELATIVE,
                            pan=(target_x - frame_width/2) / frame_width,
                            tilt=-(target_y - frame_height/2) / frame_height,
                            zoom=0.1 if zoom_factor > 1.2 else 0.0,
                            target_track_id=target.track_id
                        )
                        bus.publish(EventTopics.PTZ_COMMANDS, ptz_event)
                        
                        logger.debug(
                            "ptz_adjustment_sent",
                            track_id=target.track_id,
                            zoom_factor=zoom_factor
                        )
                else:
                    # No target, reset
                    if current_target_id is not None:
                        logger.info("no_target_available")
                        current_target_id = None
                
                # Log FPS
                if frame_number % 30 == 0:
                    fps = rtsp_client.get_fps()
                    logger.info(
                        "processing_status",
                        frame=frame_number,
                        fps=fps,
                        detections=len(detections),
                        tracks=len(tracks)
                    )
            
            except Exception as e:
                logger.error(
                    "processing_error",
                    error=str(e),
                    frame=frame_number,
                    exc_info=True
                )
    
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    
    except Exception as e:
        logger.error(
            "service_error",
            error=str(e),
            exc_info=True
        )
    
    finally:
        logger.info("vision_service_stopping")
        if 'rtsp_client' in locals():
            rtsp_client.stop()


if __name__ == "__main__":
    main()
