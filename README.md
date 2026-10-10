# Emergency Resource Allocator Backend

FastAPI & MongoDB foundation for HLTH-02 Real-Time Emergency Resource Allocator. Provides hospital registration, login, profile management, and operational resource metrics (beds, ICU, ventilators, oxygen cylinders, on-duty doctors, and triage status).

## Setup and run on Windows

From this project directory:

```cmd
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Environment Configuration

Configure in `.env`:
- `MONGODB_URL`: MongoDB connection string (default: `mongodb://localhost:27017`)
- `DATABASE_NAME`: Database name (default: `emergency_triage_db`)
- `JWT_SECRET_KEY`: Random secret of at least 32 characters; required in production
- `ENVIRONMENT`: `development` locally or `production` on deployment
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
- `POST /hospitals/login`: Verify credentials and issue JWT access and refresh tokens.
- `POST /hospitals/refresh`: Exchange a valid refresh token for a new token pair.
- `GET /hospitals/public`: Public list of active hospital names and locations; no login required.
- `GET /hospitals/`: List all registered hospitals; requires a bearer access token.
- `GET /hospitals/{hospital_id}`: Retrieve single hospital details; requires a bearer access token.
- `PUT /hospitals/{hospital_id}`: Update hospital profile & capacity details; requires a bearer access token.
- `PATCH /hospitals/{hospital_id}`: Partial update hospital profile; requires a bearer access token.
- `PATCH /hospitals/{hospital_id}/availability`: Update hospital bed counts; requires a bearer access token.

### Hospitals Operational Data (`/hospitals-data`)
- `POST /hospitals-data/`: Create operational resource entry (beds, ICU, ventilators, oxygen, doctor aggregates, doctor details, and triage status).
- `GET /hospitals-data/`: List all recent operational data records.
- `GET /hospitals-data/{data_id}`: Get single operational record by ID.
- `PUT /hospitals-data/{data_id}`: Update operational record and resource counts.
- `PATCH /hospitals-data/{data_id}`: Partial update operational record.
- `DELETE /hospitals-data/{data_id}`: Delete operational data record.
- `GET /hospitals-data/hospital/{hospital_id}/latest`: Get latest metrics for a hospital.
- `GET /hospitals-data/hospital/{hospital_id}/history`: Get historical logs for a hospital.

Each `hospitals-data` record can include a `doctors` array. Every doctor entry
requires `doctor_id`, `name`, `specialization`, and `is_available`:

```json
{
  "hospital_id": "507f1f77bcf86cd799439011",
  "doctors": [
    {
      "doctor_id": "DOC-001",
      "name": "Dr. Asha Rao",
      "specialization": "Emergency Medicine",
      "is_available": true
    }
  ]
}
```

The existing `doctors_total` and `doctors_available` fields remain aggregate
summary values. The detailed list is optional for backward compatibility and
defaults to an empty list.

### Health
- `GET /health`: Health check (`{"status": "ok"}`).

Interactive Swagger UI documentation is available at `http://127.0.0.1:8000/docs`.

## JWT authentication

Set `JWT_SECRET_KEY` to a long random value in the environment; never use the
development fallback in production. After registration, call
`POST /hospitals/login`:

```json
{
  "registration_number": "CGH-001",
  "password": "securepassword123"
}
```

Send the returned access token on protected requests:

```text
Authorization: Bearer <access_token>
```

Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES`. Refresh tokens expire
after `REFRESH_TOKEN_EXPIRE_DAYS` and must only be sent to
`POST /hospitals/refresh`.

## Vercel deployment

The repository includes `vercel.json`, which maps `app/main.py` to the Vercel
Python runtime. Configure these Vercel project environment variables:

- `MONGODB_URL`: MongoDB Atlas `mongodb+srv://...` connection string
- `DATABASE_NAME`: Atlas database name
- `JWT_SECRET_KEY`: long random secret, at least 32 characters
- `FRONTEND_ORIGIN`: `https://emergency-triage-six.vercel.app`
- `ENVIRONMENT`: `production`

Production startup fails clearly if the database variables, TLS-enabled Atlas
URI, or JWT secret are missing. The MongoDB client is cached and configured
with bounded connection and server-selection timeouts for warm serverless
invocations.
