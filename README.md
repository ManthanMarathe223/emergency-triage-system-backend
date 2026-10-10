# Emergency Resource Allocator Backend

FastAPI foundation for HLTH-02 Real-Time Emergency Resource Allocator. The
current phase provides hospital registration and reported bed availability.
Emergency assignment, ranking, authentication, and reservation workflows are
intentionally not implemented yet.

## Setup and run on Windows

From this project directory:

```cmd
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The default development database is `emergency_resource.db`. Set
`DATABASE_URL` to use another SQLAlchemy-supported database URL. `FRONTEND_ORIGIN`
can add one additional legitimate frontend origin.

## API

- `GET /health` returns `{"status":"ok"}`.
- `POST /hospitals/` registers a hospital.
- `GET /hospitals/` lists hospitals.
- `GET /hospitals/{hospital_id}` retrieves one hospital.
- `PATCH /hospitals/{hospital_id}/availability` updates total and available beds.

Example registration request:

```json
{
  "name": "City General Hospital",
  "registration_number": "CGH-001",
  "address": "1 Main Street",
  "latitude": 18.5204,
  "longitude": 73.8567,
  "total_beds": 100,
  "available_beds": 40,
  "is_active": true
}
```

Open `http://127.0.0.1:8000/docs` after starting the server. Use `POST
/hospitals/` with the example, copy the returned `id`, then try the list,
detail, and availability endpoints. Invalid coordinates, negative bed counts,
and available beds greater than total beds return `422`; duplicate registration
numbers return `409`; unknown IDs return `404`.

The configured production frontend origin is
`https://emergency-triage-six.vercel.app`. CORS configuration does not itself
claim that the deployed frontend is connected to a running backend.
