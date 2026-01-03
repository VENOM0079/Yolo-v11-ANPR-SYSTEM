"""
ANPR Service Main Entry Point.
Processes ANPR requests from message bus.
"""
import sys
import signal
sys.path.append('/app')

from shared.utils.logger import setup_logging, get_logger
from shared.config.loader import config
from shared.events.message_bus import MessageBus
from shared.events.schemas import ANPRRequest, ANPRResult, EventTopics
from services.anpr_service.ocr_engine import ANPREngine

# Setup logging
logger = setup_logging("anpr-service", log_level="INFO", log_format="json")

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("shutdown_signal_received")
    running = False


def process_anpr_request(data: dict, engine: ANPREngine, bus: MessageBus):
    """
    Process ANPR request.
    
    Args:
        data: Request data dictionary
        engine: ANPREngine instance
        bus: MessageBus instance
    """
    try:
        request = ANPRRequest(**data)
        
        logger.info(
            "processing_anpr_request",
            request_id=request.request_id,
            track_id=request.track_id,
            crop_path=request.plate_crop_path
        )
        
        # Run ANPR
        plate_text, confidence, raw_detections = engine.recognize(
            request.plate_crop_path
        )
        
        # Create result event
        result = ANPRResult(
            request_id=request.request_id,
            track_id=request.track_id,
            plate_text=plate_text or "",
            confidence=confidence,
            plate_crop_path=request.plate_crop_path,
            validated=plate_text is not None,
            raw_detections=raw_detections
        )
        
        # Publish result
        bus.publish(EventTopics.ANPR_RESULTS, result)
        
        if plate_text:
            logger.info(
                "anpr_success",
                request_id=request.request_id,
                track_id=request.track_id,
                plate=plate_text,
                confidence=confidence
            )
        else:
            logger.warning(
                "anpr_failed",
                request_id=request.request_id,
                track_id=request.track_id,
                confidence=confidence
            )
    
    except Exception as e:
        logger.error(
            "anpr_processing_error",
            error=str(e),
            exc_info=True
        )


def main():
    """Main service entry point."""
    global running
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("anpr_service_starting")
    
    try:
        # Initialize ANPR engine
        logger.info("initializing_anpr_engine")
        engine = ANPREngine()
        
        # Initialize message bus
        logger.info("connecting_to_message_bus")
        redis_config = config.get_section('events').get('redis', {})
        bus = MessageBus(
            host=redis_config.get('host', 'localhost'),
            port=redis_config.get('port', 6379),
            password=redis_config.get('password'),
            stream_max_len=redis_config.get('stream_max_len', 10000)
        )
        
        # Subscribe to ANPR requests
        logger.info("subscribing_to_anpr_requests")
        bus.subscribe(
            topic=EventTopics.ANPR_REQUESTS,
            consumer_group="anpr-service",
            consumer_name="anpr-service-1",
            callback=lambda data: process_anpr_request(data, engine, bus),
            block_ms=1000,
            count=5
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
        logger.info("anpr_service_stopping")


if __name__ == "__main__":
    main()
