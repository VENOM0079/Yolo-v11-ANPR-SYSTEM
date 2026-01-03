"""
UI Service - FastAPI Web Dashboard.
Provides live view, PTZ control, event search, and system health.
"""
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
import sys
import cv2
import numpy as np
from pathlib import Path
sys.path.append('/app')

from shared.utils.logger import setup_logging, get_logger
from shared.config.loader import config
from shared.events.message_bus import MessageBus
from services.storage_service.db_models import (
    create_database_engine, get_session_maker,
    ANPRRecord
)

# Setup logging
logger = setup_logging("ui-service", log_level="INFO", log_format="json")

# Initialize FastAPI
app = FastAPI(title="PTZ Camera System Dashboard")

# Setup templates (create templates directory)
templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

# Initialize database
db_config = config.get_section('storage').get('database', {})
conn_string = (
    f"postgresql://{db_config['username']}:{db_config['password']}"
    f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
)
engine = create_database_engine(conn_string)
SessionMaker = get_session_maker(engine)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "ui-service"
    }


@app.get("/api/anpr/search")
async def search_plates(plate: str = None, limit: int = 100):
    """
    Search ANPR records.
    
    Query params:
        plate: Plate text to search for (partial match)
        limit: Max results to return
    """
    session = SessionMaker()
    
    query = session.query(ANPRRecord)
    
    if plate:
        query = query.filter(ANPRRecord.plate_text.ilike(f"%{plate}%"))
    
    records = query.order_by(ANPRRecord.timestamp.desc()).limit(limit).all()
    
    results = []
    for record in records:
        results.append({
            "timestamp": record.timestamp.isoformat(),
            "track_id": record.track_id,
            "plate_text": record.plate_text,
            "confidence": record.confidence,
            "validated": record.validated,
            "crop_path": record.plate_crop_path
        })
    
    session.close()
    
    return {"results": results, "count": len(results)}


@app.get("/api/stats")
async def get_statistics():
    """Get system statistics."""
    session = SessionMaker()
    
    try:
        total_plates = session.query(ANPRRecord).count()
        validated_plates = session.query(ANPRRecord).filter_by(validated=True).count()
        
        # Get recent plates
        recent = session.query(ANPRRecord).order_by(
            ANPRRecord.timestamp.desc()
        ).limit(10).all()
        
        recent_list = [{
            "timestamp": r.timestamp.isoformat(),
            "plate": r.plate_text,
            "confidence": r.confidence
        } for r in recent]
        
        return {
            "total_plates": total_plates,
            "validated_plates": validated_plates,
            "recent_plates": recent_list
        }
    finally:
        session.close()


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket for real-time event stream."""
    await websocket.accept()
    
    # Initialize message bus
    redis_config = config.get_section('events').get('redis', {})
    bus = MessageBus(
        host=redis_config.get('host', 'localhost'),
        port=redis_config.get('port', 6379)
    )
    
    try:
        while True:
            # In production, subscribe to events and push to websocket
            # For now, send keepalive
            await websocket.send_json({
                "type": "keepalive",
                "timestamp": "now"
            })
            
            import asyncio
            await asyncio.sleep(5)
    
    except Exception as e:
        logger.error("websocket_error", error=str(e))
    finally:
        await websocket.close()


if __name__ == "__main__":
    import uvicorn
    
    ui_config = config.get_section('ui')
    port = ui_config.get('port', 8080)
    host = ui_config.get('host', '0.0.0.0')
    
    logger.info("ui_service_starting", host=host, port=port)
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
