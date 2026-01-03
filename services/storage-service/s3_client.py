"""
MinIO/S3 Client for media storage.
"""
from minio import Minio
from minio.error import S3Error
from pathlib import Path
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger
from shared.config.loader import config

logger = get_logger(__name__)


class S3Client:
    """MinIO/S3 client for storing plate crops and media."""
    
    def __init__(self):
        """Initialize S3 client."""
        storage_config = config.get_section('storage').get('object_storage', {})
        
        self.endpoint = storage_config.get('endpoint')
        self.access_key = storage_config.get('access_key')
        self.secret_key = storage_config.get('secret_key')
        self.bucket = storage_config.get('bucket')
        self.secure = storage_config.get('secure', False)
        
        # Initialize MinIO client
        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure
        )
        
        # Create bucket if not exists
        self._ensure_bucket_exists()
        
        logger.info(
            "s3_client_initialized",
            endpoint=self.endpoint,
            bucket=self.bucket
        )
    
    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("bucket_created", bucket=self.bucket)
        except S3Error as e:
            logger.error(
                "bucket_creation_failed",
                bucket=self.bucket,
                error=str(e)
            )
    
    def upload_file(self, local_path: str, object_name: str) -> bool:
        """
        Upload file to S3.
        
        Args:
            local_path: Local file path
            object_name: S3 object name
        
        Returns:
            True if successful
        """
        try:
            self.client.fput_object(
                self.bucket,
                object_name,
                local_path
            )
            
            logger.debug(
                "file_uploaded",
                local_path=local_path,
                object_name=object_name
            )
            
            return True
        
        except S3Error as e:
            logger.error(
                "upload_failed",
                local_path=local_path,
                object_name=object_name,
                error=str(e)
            )
            return False
    
    def get_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        """
        Get presigned URL for object.
        
        Args:
            object_name: S3 object name
            expires_seconds: URL expiration time
        
        Returns:
            Presigned URL
        """
        try:
            url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=expires_seconds
            )
            return url
        except S3Error as e:
            logger.error(
                "get_url_failed",
                object_name=object_name,
                error=str(e)
            )
            return ""
    
    def delete_object(self, object_name: str) -> bool:
        """Delete object from S3."""
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.debug("object_deleted", object_name=object_name)
            return True
        except S3Error as e:
            logger.error(
                "delete_failed",
                object_name=object_name,
                error=str(e)
            )
            return False
