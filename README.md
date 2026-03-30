# HireFlow AI

AI-enabled HRMS built with FastAPI + Next.js.

## What is implemented

- Employee directory with search, profile updates, and document/profile image upload
- Recruitment with job postings, candidate pipeline, and stage updates
- Leave and attendance management with balances and approvals
- Performance review cycles with self + manager reviews
- Onboarding checklists and policy chatbot endpoint
- Payroll records and analytics dashboard
- JWT authentication with role-aware route protection (admin/manager/employee)
- AI endpoints wired through Google Gemini service (with graceful fallback messaging)

## Seeded demo data (auto-created on first backend startup)

- 11 employee profiles across Engineering, Human Resources, and Sales
- 3 job postings and sample candidates
- 5 leave requests (approved + pending mix)
- Attendance samples for recent working days
- Payroll records for seeded employees
- Policy document and onboarding checklist
- Default login:
  - `admin@hireflow.ai` / `admin123`

## Tech stack

- Backend: FastAPI, SQLAlchemy, SQLite, JWT
- Frontend: Next.js 14 (App Router), TypeScript, Tailwind CSS
- AI: Google Gemini (via `google-generativeai`)
- Deployment: Docker + Docker Compose

## Project structure

```text
.
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── services/
│   ├── ai/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/app/
│   ├── src/components/
│   ├── src/lib/
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Environment configuration

Use `.env.example` as reference.

Key variables:

- `SECRET_KEY`
- `DATABASE_URL` (default: `sqlite:///./hrms.db`)
- `GEMINI_API_KEY` (required for AI features)
- `NEXT_PUBLIC_API_URL` (frontend API base URL)

## Run locally (without Docker)

### 1) Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# create backend/.env (recommended)
cp ../.env.example .env

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Backend endpoints:

- API root: `http://localhost:8000/`
- Health: `http://localhost:8000/api/health`
- Swagger: `http://localhost:8000/docs`

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend app:

- `http://localhost:3000`

## Run with Docker

From repo root:

```bash
cp .env.example .env
# edit .env if needed

docker-compose up --build
```

Services:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

## Core API groups

- Auth: `/api/auth/*`
- Employees: `/api/employees*`
- Documents: `/api/documents*`
- Recruitment: `/api/jobs*` (including `/api/jobs/{job_id}/candidates/*` and `/api/jobs/{job_id}/compare`)
- Leave: `/api/leaves*`
- Attendance: `/api/attendance*`
- Performance: `/api/reviews*`
- Onboarding: `/api/onboarding*`
- HR Chat Assistant: `/api/chat`, `/api/chat/history`, `/api/chat/frequent-questions`
- Payroll: `/api/payroll*`
- Analytics: `/api/analytics*`
- AI utilities: `/api/ai/*`

## Public frontend pages

- Terms & Conditions: `/terms-and-conditions`
- Meet the Team: `/meet-the-team`

## Notes

- Database is SQLite for development.
- Seed data runs only when no users exist.
- If `GEMINI_API_KEY` is missing, non-AI flows still work; AI routes will return fallback/error content depending on endpoint behavior.

## Troubleshooting

- Port busy (`8000` or `3000`): stop old processes and restart.
- Frontend cannot reach backend: verify `NEXT_PUBLIC_API_URL`.
- AI output missing: verify `GEMINI_API_KEY` in backend environment.
