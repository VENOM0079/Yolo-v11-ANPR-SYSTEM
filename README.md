# PTZ Camera Automation System

Production-grade system for automated vehicle detection, PTZ camera control, and ANPR (Automatic Number Plate Recognition) from moving vehicles using YOLOv11, multi-object tracking, and optical zoom.

##  Features

- **Real-time Vehicle Detection**: YOLOv11-based detection for cars, trucks, buses, and motorcycles
- **Multi-Object Tracking**: Persistent vehicle tracking with trajectory history and velocity estimation
- **Automated PTZ Control**: ONVIF-based camera steering with preset sweeps, hysteresis, and rate limiting
- **ANPR/OCR**: License plate recognition using EasyOCR with preprocessing and validation
- **Event Pipeline**: Redis Streams-based message bus for decoupled services
- **Data Persistence**: PostgreSQL for metadata, MinIO/S3 for media storage
- **Web Dashboard**: Live statistics, plate search, and system monitoring
- **Production-Ready**: Dockerized microservices with GPU support

##  Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  RTSP       │───>│   Vision     │───>│ PTZ         │
│  Stream     │    │   Service    │    │ Controller  │
└─────────────┘    └──────┬───────┘    └─────────────┘
                          │
                    ┌─────▼─────┐
                    │   Redis   │
                    │  Streams  │
                    └─────┬─────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────▼────┐      ┌─────▼──────┐   ┌─────▼─────┐
   │  ANPR   │      │  Storage   │   │ UI        │
   │ Service │      │  Service   │   │ Service   │
   └─────────┘      └────────────┘   └───────────┘
                          │
               ┌──────────┼──────────┐
               │          │          │
          ┌────▼───┐ ┌────▼────┐ ┌──▼──────┐
          │Postgres│ │  MinIO  │ │Dashboard│
          └────────┘ └─────────┘ └─────────┘
```

##  Quick Start

### Prerequisites

- Docker & Docker Compose
- NVIDIA GPU with CUDA support (recommended)
- RTSP-capable PTZ camera with ONVIF support
- At least 8GB RAM, 20GB disk space

### Installation

1. **Clone and setup:**
   ```bash
   cd C:\Users\A.M\.gemini\antigravity\scratch\ptz-camera-system
   ```

2. **Copy environment configuration:**
   ```bash
   copy .env.example .env
   ```

3. **Edit `.env` file with your camera details:**
   ```bash
   RTSP_URL=rtsp://admin:password@192.168.1.100:554/stream1
   PTZ_ONVIF_HOST=192.168.1.100
   PTZ_USERNAME=admin
   PTZ_PASSWORD=yourpassword
   ```

4. **Download YOLOv11 model:**
   ```bash
   mkdir models
   # Download YOLOv11n.pt from Ultralytics or use:
   # python -c "from ultralytics import YOLO; YOLO('yolov11n.pt')"
   ```

5. **Start all services:**
   ```bash
   docker-compose up -d
   ```

6. **Access the dashboard:**
   Open http://localhost:8080 in your browser

##  Project Structure

```
ptz-camera-system/
├── shared/                    # Shared utilities and configuration
│   ├── config/               # Configuration management
│   ├── events/               # Event schemas and message bus
│   └── utils/                # Logging, RTSP client
├── services/
│   ├── ptz-controller/       # PTZ camera control
│   ├── vision-service/       # YOLOv11 detection & tracking
│   ├── anpr-service/         # License plate recognition
│   ├── storage-service/      # Database & S3 persistence
│   └── ui-service/           # Web dashboard
├── docker/                   # Dockerfiles for each service
├── models/                   # ML model weights
├── docker-compose.yml        # Service orchestration
├── requirements.txt          # Python dependencies
└── .env.example             # Configuration template
```

##  Configuration

### Key Configuration Files

- **`.env`**: Environment variables for credentials and endpoints
- **`shared/config/config.yaml`**: Detailed system configuration
 
### Important Settings

#### Detection & Tracking
```yaml
detection:
  confidence_threshold: 0.5
  iou_threshold: 0.45

tracking:
  max_age: 30              # Frames to keep track without detection
  min_hits: 3              # Detections required to confirm track
```

#### PTZ Control
```yaml
ptz:
  control:
    move_rate_limit_ms: 2000   # Min time between movements
    hysteresis_pixels: 50      # Dead zone to prevent jitter
    pan_speed: 0.5
    zoom_step: 0.1
```

#### ANPR
```yaml
anpr:
  min_confidence: 0.6
  min_plate_height_pixels: 150
  zoom_target_plate_height: 200
```

##  Services

### PTZ Controller
- ONVIF camera communication
- Preset management and sweeps
- Movement with rate limiting and hysteresis
- Idle behavior and auto-return

### Vision Service
- YOLOv11 vehicle detection
- Multi-object tracking (ByteTrack)
- Target prioritization (proximity, ROI, velocity)
- Plate region proposal

### ANPR Service
- EasyOCR-based plate recognition
- Image preprocessing (denoise, CLAHE, threshold)
- Format validation with regex patterns
- Confidence scoring

### Storage Service
- PostgreSQL for metadata (detections, tracks, ANPR)
- MinIO/S3 for plate crops and media
- Event persistence from message bus
- Retention policy management

### UI Service
- FastAPI web server
- Real-time statistics dashboard
- Plate search functionality
- Live event stream (WebSocket)

##  API Endpoints

### Health Check
```
GET /api/health
```

### ANPR Search
```
GET /api/anpr/search?plate=ABC123&limit=100
```

### Statistics
```
GET /api/stats
```

### WebSocket Events
```
WS /ws/events
```

##  Docker Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f vision-service

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose up -d --build

# View service status
docker-compose ps
```

##  Monitoring

- **Logs**: JSON-formatted structured logs in each container
- **Health**: Check `/api/health` for service status
- **Database**: Connect to PostgreSQL on `localhost:5432`
- **MinIO Console**: Access at `http://localhost:9001`
- **Redis**: Monitor streams with `redis-cli`

##  Troubleshooting

### RTSP Connection Issues
- Verify camera IP and credentials in `.env`
- Check network connectivity: `ping <camera_ip>`
- Test RTSP stream: `ffplay rtsp://...`

### PTZ Not Moving
- Verify ONVIF port (usually 80 or 8080)
- Check camera supports ONVIF Profile S
- Review logs: `docker-compose logs ptz-controller`

### Low Detection Accuracy
- Adjust `confidence_threshold` in config.yaml
- Ensure adequate lighting conditions
- Consider using larger YOLOv11 model (yolov11m.pt)

### ANPR Failures
- Check plate crops quality in `/app/data/plate_crops`
- Adjust zoom settings for higher resolution
- Verify plate format patterns match your region

##  Performance Optimization

- **GPU**: Ensure NVIDIA Docker runtime is configured
- **Model Size**: Use YOLOv11n for speed, YOLOv11x for accuracy
- **Frame Rate**: Adjust RTSP buffer size and decode threads
- **Database**: Add indexes for frequently queried columns
- **Storage**: Configure retention policies to limit disk usage

##  Security & Privacy

- Store credentials in `.env` (never commit to git)
- Use TLS for RTSP streams in production
- Enable face masking if required by privacy laws
- Configure data retention policies
- Implement access controls on dashboard
- Audit logging enabled by default

##  License

This project template is provided as-is for educational and development purposes.

##  Credits

- **YOLOv11**: Ultralytics
- **EasyOCR**: JaidedAI
- **ONVIF**: onvif-zeep
- **FastAPI**: Sebastián Ramírez

##  Support

For issues and questions, refer to service logs and configuration documentation.

---

**Built with for production-grade PTZ automation**
