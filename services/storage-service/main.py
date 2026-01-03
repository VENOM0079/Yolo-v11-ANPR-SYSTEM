"""
Storage Service Main Entry Point.
Persists events to database and uploads media to S3.
"""
import sys
import signal
from pathlib import Path
sys.path.append('/app')

from shared.utils.logger import setup_logging, get_logger
from shared.config.loader import config
from shared.events.message_bus import MessageBus
from shared.events.schemas import (
    DetectionEvent, TrackingEvent, PTZEvent, ANPRResult, EventTopics
)
from services.storage_service.db_models import (
    create_database_engine, get_session_maker,
    Detection, VehicleTrack, PTZAction, ANPRRecord
)
from services.storage_service.s3_client import S3Client

# Setup logging
logger = setup_logging("storage-service", log_level="INFO", log_format="json")

# Global flag
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("shutdown_signal_received")
    running = False


def process_detection(data: dict, session_maker):
    """Store detection event."""
    try:
        event = DetectionEvent(**data)
        session = session_maker()
        
        detection = Detection(
            event_id=event.event_id,
            timestamp=event.timestamp,
            frame_number=event.frame_number,
            bbox_x1=event.bbox.x1,
            bbox_y1=event.bbox.y1,
            bbox_x2=event.bbox.x2,
            bbox_y2=event.bbox.y2,
            vehicle_class=event.vehicle_class,
            confidence=event.confidence,
            frame_width=event.frame_width,
            frame_height=event.frame_height
        )
        
        session.add(detection)
        session.commit()
        session.close()
        
        logger.debug("detection_stored", event_id=event.event_id)
    except Exception as e:
        logger.error("detection_storage_failed", error=str(e))


def process_tracking(data: dict, session_maker):
    """Store tracking event."""
    try:
        event = TrackingEvent(**data)
        session = session_maker()
        
        # Upsert track
        track = session.query(VehicleTrack).filter_by(track_id=event.track_id).first()
        
        if track:
            track.last_seen = event.timestamp
            track.total_frames = event.hits
            track.trajectory = event.trajectory
        else:
            track = VehicleTrack(
                track_id=event.track_id,
                first_seen=event.timestamp,
                last_seen=event.timestamp,
                vehicle_class=event.vehicle_class,
                total_frames=event.hits,
                trajectory=event.trajectory
            )
            session.add(track)
        
        session.commit()
        session.close()
        
        logger.debug("track_updated", track_id=event.track_id)
    except Exception as e:
        logger.error("tracking_storage_failed", error=str(e))


def process_ptz(data: dict, session_maker):
    """Store PTZ action."""
    try:
        event = PTZEvent(**data)
        session = session_maker()
        
        action = PTZAction(
            event_id=event.event_id,
            timestamp=event.timestamp,
            command=event.command,
            pan=event.pan,
            tilt=event.tilt,
            zoom=event.zoom,
            preset_id=event.preset_id,
            target_track_id=event.target_track_id,
            success=event.success,
            error_message=event.error_message
        )
        
        session.add(action)
        session.commit()
        session.close()
        
        logger.debug("ptz_action_stored", event_id=event.event_id)
    except Exception as e:
        logger.error("ptz_storage_failed", error=str(e))


def process_anpr(data: dict, session_maker, s3_client):
    """Store ANPR result and upload crop."""
    try:
        event = ANPRResult(**data)
        session = session_maker()
        
        # Upload crop to S3
        crop_path = Path(event.plate_crop_path)
        if crop_path.exists():
            s3_key = f"plates/{crop_path.name}"
            s3_client.upload_file(str(crop_path), s3_key)
        
        # Store record
        record = ANPRRecord(
            event_id=event.event_id,
            timestamp=event.timestamp,
            request_id=event.request_id,
            track_id=event.track_id,
            plate_text=event.plate_text,
            confidence=event.confidence,
            plate_crop_path=event.plate_crop_path,
            validated=event.validated,
            raw_detections=event.raw_detections
        )
        
        session.add(record)
        session.commit()
        session.close()
        
        logger.info(
            "anpr_stored",
            event_id=event.event_id,
            plate=event.plate_text
        )
    except Exception as e:
        logger.error("anpr_storage_failed", error=str(e))


def main():
    """Main service entry point."""
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("storage_service_starting")
    
    try:
        # Initialize database
        db_config = config.get_section('storage').get('database', {})
        conn_string = (
            f"postgresql://{db_config['username']}:{db_config['password']}"
            f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        )
        engine = create_database_engine(conn_string)
        session_maker = get_session_maker(engine)
        
        # Initialize S3 client
        s3_client = S3Client()
        
        # Initialize message bus
        redis_config = config.get_section('events').get('redis', {})
        bus = MessageBus(
            host=redis_config.get('host', 'localhost'),
            port=redis_config.get('port', 6379),
            password=redis_config.get('password')
        )
        
        # Subscribe to all event topics (run in separate threads/processes in production)
        import threading
        
        threads = [
            threading.Thread(
                target=bus.subscribe,
                args=(
                    EventTopics.DETECTIONS,
                    "storage-service",
                    "storage-detections",
                    lambda d: process_detection(d, session_maker)
                ),
                daemon=True
            ),
            threading.Thread(
                target=bus.subscribe,
                args=(
                    EventTopics.TRACKING,
                    "storage-service",
                    "storage-tracking",
                    lambda d: process_tracking(d, session_maker)
                ),
                daemon=True
            ),
            threading.Thread(
                target=bus.subscribe,
                args=(
                    EventTopics.PTZ_COMMANDS,
                    "storage-service",
                    "storage-ptz",
                    lambda d: process_ptz(d, session_maker)
                ),
                daemon=True
            ),
            threading.Thread(
                target=bus.subscribe,
                args=(
                    EventTopics.ANPR_RESULTS,
                    "storage-service",
                    "storage-anpr",
                    lambda d: process_anpr(d, session_maker, s3_client)
                ),
                daemon=True
            )
        ]
        
        for t in threads:
            t.start()
        
        # Keep main thread alive
        for t in threads:
            t.join()
    
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as e:
        logger.error("service_error", error=str(e), exc_info=True)
    finally:
        logger.info("storage_service_stopping")


if __name__ == "__main__":
    main()
