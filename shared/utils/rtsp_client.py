"""RTSP stream client with reconnection and frame buffering."""
import cv2
import time
import queue
import threading
from typing import Optional, Tuple
import numpy as np
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class RTSPClient:
    """
    RTSP stream client with automatic reconnection and frame buffering.
    """
    
    def __init__(
        self,
        rtsp_url: str,
        backup_url: Optional[str] = None,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 10,
        buffer_size: int = 30
    ):
        """
        Initialize RTSP client.
        
        Args:
            rtsp_url: Primary RTSP stream URL
            backup_url: Backup RTSP stream URL (optional)
            reconnect_delay: Seconds between reconnection attempts
            max_reconnect_attempts: Maximum reconnection attempts
            buffer_size: Frame buffer size
        """
        self.primary_url = rtsp_url
        self.backup_url = backup_url
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame_queue = queue.Queue(maxsize=buffer_size)
        self.running = False
        self.capture_thread: Optional[threading.Thread] = None
        
        self.frame_count = 0
        self.last_frame_time = 0
        self.fps = 0.0
        
        logger.info("rtsp_client_initialized", url=rtsp_url)
    
    def connect(self) -> bool:
        """
        Connect to RTSP stream.
        
        Returns:
            True if connection successful
        """
        urls = [self.primary_url]
        if self.backup_url:
            urls.append(self.backup_url)
        
        for url in urls:
            for attempt in range(self.max_reconnect_attempts):
                try:
                    logger.info(
                        "connecting_to_stream",
                        url=url,
                        attempt=attempt + 1
                    )
                    
                    self.cap = cv2.VideoCapture(url)
                    
                    # Set buffer size to minimum for low latency
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    
                    # Test read
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        logger.info(
                            "stream_connected",
                            url=url,
                            frame_shape=frame.shape
                        )
                        return True
                    
                    self.cap.release()
                    self.cap = None
                
                except Exception as e:
                    logger.error(
                        "connection_failed",
                        url=url,
                        attempt=attempt + 1,
                        error=str(e)
                    )
                
                if attempt < self.max_reconnect_attempts - 1:
                    time.sleep(self.reconnect_delay)
        
        logger.error("all_connection_attempts_failed")
        return False
    
    def start(self):
        """Start frame capture thread."""
        if self.running:
            logger.warning("capture_already_running")
            return
        
        if not self.cap or not self.cap.isOpened():
            if not self.connect():
                raise RuntimeError("Failed to connect to RTSP stream")
        
        self.running = True
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True
        )
        self.capture_thread.start()
        logger.info("capture_thread_started")
    
    def stop(self):
        """Stop frame capture thread."""
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=5.0)
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        logger.info("capture_stopped")
    
    def _capture_loop(self):
        """Main capture loop running in background thread."""
        consecutive_failures = 0
        max_consecutive_failures = 30
        
        while self.running:
            try:
                if not self.cap or not self.cap.isOpened():
                    logger.warning("stream_disconnected_reconnecting")
                    if not self.connect():
                        time.sleep(self.reconnect_delay)
                        continue
                    consecutive_failures = 0
                
                ret, frame = self.cap.read()
                
                if not ret or frame is None:
                    consecutive_failures += 1
                    logger.warning(
                        "frame_read_failed",
                        consecutive_failures=consecutive_failures
                    )
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error("too_many_failures_reconnecting")
                        self.cap.release()
                        self.cap = None
                        consecutive_failures = 0
                    
                    time.sleep(0.1)
                    continue
                
                # Reset failure counter on success
                consecutive_failures = 0
                
                # Update metrics
                self.frame_count += 1
                current_time = time.time()
                if self.last_frame_time > 0:
                    self.fps = 1.0 / (current_time - self.last_frame_time)
                self.last_frame_time = current_time
                
                # Add to queue (drop oldest if full)
                try:
                    self.frame_queue.put_nowait((self.frame_count, frame))
                except queue.Full:
                    # Drop oldest frame
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put_nowait((self.frame_count, frame))
                    except queue.Empty:
                        pass
            
            except Exception as e:
                logger.error(
                    "capture_loop_error",
                    error=str(e),
                    exc_info=True
                )
                time.sleep(1.0)
    
    def read(self, timeout: float = 1.0) -> Optional[Tuple[int, np.ndarray]]:
        """
        Read next frame from buffer.
        
        Args:
            timeout: Maximum time to wait for frame
        
        Returns:
            Tuple of (frame_number, frame) or None if timeout
        """
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_fps(self) -> float:
        """Get current FPS."""
        return self.fps
    
    def get_frame_count(self) -> int:
        """Get total frames captured."""
        return self.frame_count
    
    def is_connected(self) -> bool:
        """Check if stream is connected."""
        return self.cap is not None and self.cap.isOpened()
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
