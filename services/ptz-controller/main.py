"""
PTZ Controller Service Main Entry Point.
Listens for PTZ commands and publishes status events.
"""
import sys
import signal
import time
sys.path.append('/app')

from shared.utils.logger import setup_logging, get_logger
from shared.config.loader import config
from shared.events.message_bus import MessageBus
from shared.events.schemas import PTZEvent, PTZStatusEvent, PTZCommand, EventTopics
from services.ptz_controller.onvif_client import PTZClient
from services.ptz_controller.preset_manager import PresetManager
from services.ptz_controller.controller import PTZController

# Setup logging
logger = setup_logging("ptz-controller", log_level="INFO", log_format="json")

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("shutdown_signal_received")
    running = False


def process_ptz_command(data: dict, controller: PTZController):
    """
    Process incoming PTZ command.
    
    Args:
        data: Command data dictionary
        controller: PTZController instance
    """
    try:
        event = PTZEvent(**data)
        
        logger.info(
            "processing_ptz_command",
            command=event.command,
            target_track_id=event.target_track_id
        )
        
        success = False
        error_message = None
        
        if event.command == PTZCommand.GOTO_PRESET:
            if event.preset_id:
                success = controller.preset_mgr.goto_preset_by_id(event.preset_id)
            else:
                error_message = "preset_id required for GOTO_PRESET"
        
        elif event.command == PTZCommand.MOVE_ABSOLUTE:
            if event.pan is not None and event.tilt is not None and event.zoom is not None:
                success = controller.ptz.absolute_move(
                    event.pan,
                    event.tilt,
                    event.zoom
                )
            else:
                error_message = "pan, tilt, zoom required for MOVE_ABSOLUTE"
        
        elif event.command == PTZCommand.MOVE_RELATIVE:
            if event.pan is not None and event.tilt is not None and event.zoom is not None:
                success = controller.ptz.relative_move(
                    event.pan,
                    event.tilt,
                    event.zoom
                )
            else:
                error_message = "pan, tilt, zoom required for MOVE_RELATIVE"
        
        elif event.command == PTZCommand.ZOOM:
            if event.zoom is not None:
                success = controller.ptz.relative_move(0.0, 0.0, event.zoom)
            else:
                error_message = "zoom required for ZOOM"
        
        elif event.command == PTZCommand.STOP:
            success = controller.ptz.stop()
        
        else:
            error_message = f"Unknown command: {event.command}"
        
        if not success and not error_message:
            error_message = "PTZ command execution failed"
        
        if error_message:
            logger.warning(
                "ptz_command_failed",
                command=event.command,
                error=error_message
            )
    
    except Exception as e:
        logger.error(
            "command_processing_error",
            error=str(e),
            exc_info=True
        )


def publish_status_loop(bus: MessageBus, ptz_client: PTZClient, interval_s: float = 2.0):
    """
    Periodically publish PTZ status.
    
    Args:
        bus: MessageBus instance
        ptz_client: PTZClient instance
        interval_s: Status publish interval in seconds
    """
    while running:
        try:
            status = ptz_client.get_status()
            
            status_event = PTZStatusEvent(
                pan=status.get('pan', 0.0),
                tilt=status.get('tilt', 0.0),
                zoom=status.get('zoom', 0.0),
                is_moving=False  # TODO: Detect movement
            )
            
            bus.publish(EventTopics.PTZ_STATUS, status_event)
            
            logger.debug("status_published", status=status)
            
            time.sleep(interval_s)
        
        except Exception as e:
            logger.error(
                "status_publish_error",
                error=str(e),
                exc_info=True
            )
            time.sleep(interval_s)


def main():
    """Main service entry point."""
    global running
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("ptz_controller_service_starting")
    
    try:
        # Initialize PTZ client
        logger.info("initializing_ptz_client")
        ptz_client = PTZClient()
        
        # Initialize preset manager
        logger.info("initializing_preset_manager")
        preset_mgr = PresetManager(ptz_client)
        
        # Initialize controller
        logger.info("initializing_ptz_controller")
        controller = PTZController(ptz_client, preset_mgr)
        
        # Perform startup sweep
        logger.info("performing_startup_sweep")
        preset_mgr.startup_sweep()
        
        # Start idle monitor
        preset_mgr.start_idle_monitor()
        
        # Initialize message bus
        logger.info("connecting_to_message_bus")
        redis_config = config.get_section('events').get('redis', {})
        bus = MessageBus(
            host=redis_config.get('host', 'localhost'),
            port=redis_config.get('port', 6379),
            password=redis_config.get('password'),
            stream_max_len=redis_config.get('stream_max_len', 10000)
        )
        
        # Start status publishing in background
        import threading
        status_thread = threading.Thread(
            target=publish_status_loop,
            args=(bus, ptz_client),
            daemon=True
        )
        status_thread.start()
        
        # Subscribe to PTZ commands
        logger.info("subscribing_to_ptz_commands")
        bus.subscribe(
            topic=EventTopics.PTZ_COMMANDS,
            consumer_group="ptz-controller",
            consumer_name="ptz-controller-1",
            callback=lambda data: process_ptz_command(data, controller),
            block_ms=1000,
            count=10
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
        logger.info("ptz_controller_service_stopping")
        preset_mgr.stop_idle_monitor()


if __name__ == "__main__":
    main()
