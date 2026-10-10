# Emergency Resource Allocator Backend

FastAPI & MongoDB foundation for HLTH-02 Real-Time Emergency Resource Allocator. Provides hospital registration, login, profile management, and operational resource metrics (beds, ICU, ventilators, oxygen cylinders, on-duty doctors, and triage status).

## Setup and run on Windows

From this project directory:

```cmd
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Environment Configuration

Configure in `.env`:
- `MONGODB_URL`: MongoDB connection string (default: `mongodb://localhost:27017`)
- `DATABASE_NAME`: Database name (default: `emergency_triage_db`)
- `FRONTEND_ORIGIN`: Allowed frontend origin for CORS (e.g. `https://emergency-triage-six.vercel.app`)

During testing, `TESTING=1` enables an in-memory MongoMock database with zero external dependencies.

## Project Architecture

```text
app/
├── hospitals/               # Hospital feature
│   ├── model.py             # Hospital document structure
│   ├── dto.py               # Request/Response schemas (Register, Login, Update, Detail)
│   ├── controller.py        # Business logic (register, login, update, list, detail)
│   └── router.py            # API routes (/hospitals)
├── hospitals_data/          # Operational resources & triage metrics feature
│   ├── model.py             # HospitalData document structure
│   ├── dto.py               # Schemas for beds, ICU, ventilators, oxygen, doctors
│   ├── controller.py        # Full CRUD logic and parent hospital bed synchronization
│   └── router.py            # API routes (/hospitals-data)
├── utils/                   # Shared utilities
│   ├── database.py          # MongoDB client, database provider, ObjectId helpers, index setup
│   └── security.py          # Password hashing and verification
└── main.py                  # FastAPI app configuration, CORS, and router registration
```

## API Endpoints

### Hospitals (`/hospitals`)
- `POST /hospitals/register`: Register a hospital with bed capacity & portal credentials.
- `POST /hospitals/login`: Simple credential verification without JWT.
- `GET /hospitals/`: List all registered hospitals.
- `GET /hospitals/{hospital_id}`: Retrieve single hospital details.
- `PUT /hospitals/{hospital_id}`: Update hospital profile & capacity details.
- `PATCH /hospitals/{hospital_id}`: Partial update hospital profile.
- `PATCH /hospitals/{hospital_id}/availability`: Update hospital bed counts.

### Hospitals Operational Data (`/hospitals-data`)
- `POST /hospitals-data/`: Create operational resource entry (beds, ICU, ventilators, oxygen, doctors on-duty, triage status).
- `GET /hospitals-data/`: List all recent operational data records.
- `GET /hospitals-data/{data_id}`: Get single operational record by ID.
- `PUT /hospitals-data/{data_id}`: Update operational record and resource counts.
- `PATCH /hospitals-data/{data_id}`: Partial update operational record.
- `DELETE /hospitals-data/{data_id}`: Delete operational data record.
- `GET /hospitals-data/hospital/{hospital_id}/latest`: Get latest metrics for a hospital.
- `GET /hospitals-data/hospital/{hospital_id}/history`: Get historical logs for a hospital.

### Health
- `GET /health`: Health check (`{"status": "ok"}`).

Interactive Swagger UI documentation is available at `http://127.0.0.1:8000/docs`.
