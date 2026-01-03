"""Redis-based message bus for event streaming."""
import json
import redis
from typing import Optional, Callable, Dict, Any
from shared.utils.logger import get_logger
from shared.events.schemas import (
    DetectionEvent, TrackingEvent, PTZEvent, PTZStatusEvent,
    ANPRRequest, ANPRResult, SystemEvent
)

logger = get_logger(__name__)


class MessageBus:
    """Redis Streams-based message bus for event distribution."""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        stream_max_len: int = 10000
    ):
        """Initialize Redis connection."""
        self.client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True
        )
        self.stream_max_len = stream_max_len
        logger.info("message_bus_initialized", host=host, port=port)
    
    def publish(self, topic: str, event: Any) -> str:
        """
        Publish event to a topic.
        
        Args:
            topic: Stream name
            event: Pydantic model instance
        
        Returns:
            Message ID
        """
        try:
            # Serialize event to JSON
            if hasattr(event, 'model_dump'):
                data = event.model_dump(mode='json')
            else:
                data = event
            
            # Add to Redis Stream
            message_id = self.client.xadd(
                topic,
                {"data": json.dumps(data)},
                maxlen=self.stream_max_len,
                approximate=True
            )
            
            logger.debug(
                "event_published",
                topic=topic,
                message_id=message_id,
                event_type=type(event).__name__
            )
            
            return message_id
        
        except Exception as e:
            logger.error(
                "publish_failed",
                topic=topic,
                error=str(e),
                exc_info=True
            )
            raise
    
    def subscribe(
        self,
        topic: str,
        consumer_group: str,
        consumer_name: str,
        callback: Callable[[Dict[str, Any]], None],
        block_ms: int = 1000,
        count: int = 10
    ):
        """
        Subscribe to a topic and process messages.
        
        Args:
            topic: Stream name
            consumer_group: Consumer group name
            consumer_name: Unique consumer identifier
            callback: Function to process each message
            block_ms: Blocking timeout in milliseconds
            count: Max messages to read per call
        """
        # Create consumer group if not exists
        try:
            self.client.xgroup_create(
                topic,
                consumer_group,
                id='0',
                mkstream=True
            )
            logger.info(
                "consumer_group_created",
                topic=topic,
                group=consumer_group
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        
        logger.info(
            "subscriber_started",
            topic=topic,
            group=consumer_group,
            consumer=consumer_name
        )
        
        while True:
            try:
                # Read messages from stream
                messages = self.client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {topic: '>'},
                    count=count,
                    block=block_ms
                )
                
                if not messages:
                    continue
                
                for stream, msgs in messages:
                    for msg_id, msg_data in msgs:
                        try:
                            # Parse JSON data
                            data = json.loads(msg_data['data'])
                            
                            # Process message
                            callback(data)
                            
                            # Acknowledge message
                            self.client.xack(topic, consumer_group, msg_id)
                            
                            logger.debug(
                                "message_processed",
                                topic=topic,
                                message_id=msg_id
                            )
                        
                        except Exception as e:
                            logger.error(
                                "message_processing_failed",
                                topic=topic,
                                message_id=msg_id,
                                error=str(e),
                                exc_info=True
                            )
            
            except KeyboardInterrupt:
                logger.info("subscriber_stopped", topic=topic)
                break
            
            except Exception as e:
                logger.error(
                    "subscriber_error",
                    topic=topic,
                    error=str(e),
                    exc_info=True
                )
    
    def get_pending_count(self, topic: str, consumer_group: str) -> int:
        """Get count of pending messages in consumer group."""
        try:
            pending = self.client.xpending(topic, consumer_group)
            return pending['pending']
        except Exception:
            return 0
    
    def trim_stream(self, topic: str, max_len: int):
        """Trim stream to maximum length."""
        self.client.xtrim(topic, maxlen=max_len, approximate=True)
        logger.info("stream_trimmed", topic=topic, max_len=max_len)
    
    def close(self):
        """Close Redis connection."""
        self.client.close()
        logger.info("message_bus_closed")
