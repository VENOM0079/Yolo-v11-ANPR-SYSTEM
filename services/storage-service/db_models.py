"""
Database Models for PTZ Camera System.
Uses SQLAlchemy for PostgreSQL persistence.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import sys
sys.path.append('/app')

from shared.utils.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()


class Detection(Base):
    """Vehicle detection record."""
    __tablename__ = 'detections'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    frame_number = Column(Integer)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    vehicle_class = Column(String(50))
    confidence = Column(Float)
    frame_width = Column(Integer)
    frame_height = Column(Integer)


class VehicleTrack(Base):
    """Vehicle tracking record."""
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, unique=True, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    vehicle_class = Column(String(50))
    total_frames = Column(Integer, default=0)
    trajectory = Column(JSON)  # List of (x, y) positions
    avg_velocity = Column(Float, default=0.0)


class PTZAction(Base):
    """PTZ camera action record."""
    __tablename__ = 'ptz_actions'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    command = Column(String(50))
    pan = Column(Float, nullable=True)
    tilt = Column(Float, nullable=True)
    zoom = Column(Float, nullable=True)
    preset_id = Column(Integer, nullable=True)
    target_track_id = Column(Integer, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(String(500), nullable=True)


class ANPRRecord(Base):
    """ANPR/Plate recognition record."""
    __tablename__ = 'anpr_records'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    request_id = Column(String(100), index=True)
    track_id = Column(Integer, index=True)
    plate_text = Column(String(20), index=True)
    confidence = Column(Float)
    plate_crop_path = Column(String(500))
    validated = Column(Boolean, default=False)
    raw_detections = Column(JSON)


class SystemEvent(Base):
    """System event log."""
    __tablename__ = 'system_events'
    
    id = Column(Integer, primary_key=True)
    event_id = Column(String(100), unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    service_name = Column(String(100))
    event_type = Column(String(100))
    message = Column(String(1000))
    metadata = Column(JSON)
    severity = Column(String(20), default='info')


def create_database_engine(connection_string: str):
    """Create database engine and tables."""
    engine = create_engine(connection_string, pool_size=10, max_overflow=20)
    Base.metadata.create_all(engine)
    logger.info("database_initialized", engine=str(engine))
    return engine


def get_session_maker(engine):
    """Get SQLAlchemy session maker."""
    return sessionmaker(bind=engine)
