import os
import json
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import settings
from database import engine, get_db, Base
from models.models import (
    User, UserRole, Employee, EmployeeStatus, Document, DocType,
    JobPosting, JobStatus, Candidate, CandidateStage,
    LeaveRequest, LeaveType, LeaveStatus, LeaveBalance,
    Attendance, AttendanceStatus,
    ReviewCycle, ReviewCycleStatus, PerformanceReview, ReviewStatus,
    OnboardingChecklist, OnboardingProgress, OnboardingStatus,
    ChatMessage, PayrollRecord, PayrollStatus,
)
from services.auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user, require_role,
)
from services.s3_service import upload_file
from ai.gemini_service import GeminiService

gemini = GeminiService()


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "employee"

class EmployeeCreate(BaseModel):
    employee_code: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    date_of_joining: Optional[date] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    employment_type: str = "full-time"
    manager_id: Optional[int] = None
    salary: float = 0
    skills: Optional[str] = None
    bio: Optional[str] = None

class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    manager_id: Optional[int] = None
    salary: Optional[float] = None
    skills: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    date_of_leaving: Optional[date] = None
    address: Optional[str] = None
    gender: Optional[str] = None

class JobPostingCreate(BaseModel):
    title: str
    description: str
    department: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    employment_type: str = "full-time"
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    status: str = "draft"
    closing_date: Optional[date] = None

class CandidateCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    resume_text: Optional[str] = None
    cover_letter: Optional[str] = None

class CandidateStageUpdate(BaseModel):
    stage: str

class LeaveRequestCreate(BaseModel):
    leave_type: str
    start_date: date
    end_date: date
    reason: Optional[str] = None

class LeaveActionRequest(BaseModel):
    action: str  # approved or rejected
    comments: Optional[str] = None

class AttendanceCreate(BaseModel):
    date: date
    status: str = "present"
    check_in: Optional[str] = None  # ISO datetime
    check_out: Optional[str] = None
    notes: Optional[str] = None

class ReviewCycleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date

class SelfAssessmentSubmit(BaseModel):
    self_rating: float
    self_comments: str
    achievements: Optional[str] = None
    goals: Optional[str] = None

class ManagerReviewSubmit(BaseModel):
    manager_rating: float
    manager_comments: str
    areas_of_improvement: Optional[str] = None

class ChatRequest(BaseModel):
    message: str

class PayrollCreate(BaseModel):
    employee_id: int
    month: int
    year: int
    basic_salary: float
    hra: float = 0
    transport_allowance: float = 0
    other_allowances: float = 0
    tax_deduction: float = 0
    pf_deduction: float = 0
    other_deductions: float = 0

class OnboardingChecklistCreate(BaseModel):
    title: str
    description: Optional[str] = None
    department: Optional[str] = None
    items: str  # JSON string of checklist items

class ChecklistProgressUpdate(BaseModel):
    completed_items: str  # comma-separated indices or JSON string

class OfferLetterRequest(BaseModel):
    employee_name: str
    designation: str
    department: str
    salary: float
    joining_date: str


# ═══════════════════════════════════════════════════════════════════════════════
# App Initialization
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="HireFlow AI - HRMS Backend",
    description="AI-Powered Human Resource Management System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


# ═══════════════════════════════════════════════════════════════════════════════
# Startup: Create Tables + Seed Data
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        _seed_data(db)
    finally:
        db.close()


def _seed_data(db: Session):
    """Seed default admin and sample data on first run."""
    if db.query(User).first() is not None:
        return

    # ── Admin user ─────────────────────────────────────────────────────────
    admin_user = User(
        email="admin@hireflow.ai",
        hashed_password=get_password_hash("admin123"),
        full_name="System Administrator",
        role="admin",
    )
    db.add(admin_user)
    db.flush()

    # ── Manager users ──────────────────────────────────────────────────────
    mgr_eng = User(email="priya.sharma@hireflow.ai", hashed_password=get_password_hash("password123"),
                   full_name="Priya Sharma", role="manager")
    mgr_hr = User(email="rahul.verma@hireflow.ai", hashed_password=get_password_hash("password123"),
                  full_name="Rahul Verma", role="manager")
    mgr_sales = User(email="anita.desai@hireflow.ai", hashed_password=get_password_hash("password123"),
                     full_name="Anita Desai", role="manager")
    db.add_all([mgr_eng, mgr_hr, mgr_sales])
    db.flush()

    # ── Employee users ─────────────────────────────────────────────────────
    emp_users = []
    emp_data = [
        ("amit.kumar@hireflow.ai", "Amit Kumar"),
        ("sneha.patel@hireflow.ai", "Sneha Patel"),
        ("vikram.singh@hireflow.ai", "Vikram Singh"),
        ("deepa.nair@hireflow.ai", "Deepa Nair"),
        ("rohan.gupta@hireflow.ai", "Rohan Gupta"),
        ("kavita.joshi@hireflow.ai", "Kavita Joshi"),
        ("arjun.reddy@hireflow.ai", "Arjun Reddy"),
        ("meera.iyer@hireflow.ai", "Meera Iyer"),
    ]
    for email, name in emp_data:
        u = User(email=email, hashed_password=get_password_hash("password123"),
                 full_name=name, role="employee")
        db.add(u)
        db.flush()
        emp_users.append(u)

    # ── Employee profiles (managers) ───────────────────────────────────────
    mgr_emp_eng = Employee(
        employee_code="EMP001", first_name="Priya", last_name="Sharma",
        email="priya.sharma@hireflow.ai", phone="+91-9876543210",
        designation="Engineering Manager", department="Engineering",
        date_of_joining=date(2022, 3, 15), salary=180000,
        skills="Python, System Design, Leadership",
        bio="Experienced engineering manager leading the backend team.",
        status="active",
    )
    mgr_emp_hr = Employee(
        employee_code="EMP002", first_name="Rahul", last_name="Verma",
        email="rahul.verma@hireflow.ai", phone="+91-9876543211",
        designation="HR Manager", department="Human Resources",
        date_of_joining=date(2021, 7, 1), salary=150000,
        skills="Recruitment, Employee Relations, Compliance",
        bio="HR leader passionate about people and culture.",
        status="active",
    )
    mgr_emp_sales = Employee(
        employee_code="EMP003", first_name="Anita", last_name="Desai",
        email="anita.desai@hireflow.ai", phone="+91-9876543212",
        designation="Sales Director", department="Sales",
        date_of_joining=date(2022, 1, 10), salary=170000,
        skills="B2B Sales, CRM, Strategy",
        bio="Sales leader with 10+ years in enterprise software.",
        status="active",
    )
    db.add_all([mgr_emp_eng, mgr_emp_hr, mgr_emp_sales])
    db.flush()

    # Link manager users to employee profiles
    mgr_eng.employee_id = mgr_emp_eng.id
    mgr_hr.employee_id = mgr_emp_hr.id
    mgr_sales.employee_id = mgr_emp_sales.id

    # ── Employee profiles ──────────────────────────────────────────────────
    employee_profiles = [
        dict(employee_code="EMP004", first_name="Amit", last_name="Kumar",
             email="amit.kumar@hireflow.ai", phone="+91-9000000001",
             designation="Senior Software Engineer", department="Engineering",
             date_of_joining=date(2023, 1, 10), salary=140000,
             skills="Python, FastAPI, PostgreSQL, Docker",
             bio="Full-stack developer with a passion for clean architecture.",
             manager_id=mgr_emp_eng.id),
        dict(employee_code="EMP005", first_name="Sneha", last_name="Patel",
             email="sneha.patel@hireflow.ai", phone="+91-9000000002",
             designation="Frontend Developer", department="Engineering",
             date_of_joining=date(2023, 4, 1), salary=120000,
             skills="React, TypeScript, Tailwind CSS",
             bio="UI/UX enthusiast creating delightful user experiences.",
             manager_id=mgr_emp_eng.id),
        dict(employee_code="EMP006", first_name="Vikram", last_name="Singh",
             email="vikram.singh@hireflow.ai", phone="+91-9000000003",
             designation="DevOps Engineer", department="Engineering",
             date_of_joining=date(2023, 6, 15), salary=135000,
             skills="AWS, Kubernetes, Terraform, CI/CD",
             bio="Infrastructure specialist ensuring 99.9% uptime.",
             manager_id=mgr_emp_eng.id),
        dict(employee_code="EMP007", first_name="Deepa", last_name="Nair",
             email="deepa.nair@hireflow.ai", phone="+91-9000000004",
             designation="HR Executive", department="Human Resources",
             date_of_joining=date(2023, 2, 20), salary=80000,
             skills="Onboarding, Payroll, HRIS",
             bio="Dedicated HR professional streamlining people operations.",
             manager_id=mgr_emp_hr.id),
        dict(employee_code="EMP008", first_name="Rohan", last_name="Gupta",
             email="rohan.gupta@hireflow.ai", phone="+91-9000000005",
             designation="Sales Executive", department="Sales",
             date_of_joining=date(2023, 5, 1), salary=100000,
             skills="Lead Generation, Salesforce, Negotiation",
             bio="Top-performing sales executive with enterprise client expertise.",
             manager_id=mgr_emp_sales.id),
        dict(employee_code="EMP009", first_name="Kavita", last_name="Joshi",
             email="kavita.joshi@hireflow.ai", phone="+91-9000000006",
             designation="Data Analyst", department="Engineering",
             date_of_joining=date(2023, 8, 1), salary=110000,
             skills="Python, SQL, Tableau, Machine Learning",
             bio="Data-driven analyst turning numbers into insights.",
             manager_id=mgr_emp_eng.id),
        dict(employee_code="EMP010", first_name="Arjun", last_name="Reddy",
             email="arjun.reddy@hireflow.ai", phone="+91-9000000007",
             designation="Account Manager", department="Sales",
             date_of_joining=date(2023, 9, 15), salary=105000,
             skills="Account Management, CRM, Client Relations",
             bio="Relationship builder managing key enterprise accounts.",
             manager_id=mgr_emp_sales.id),
        dict(employee_code="EMP011", first_name="Meera", last_name="Iyer",
             email="meera.iyer@hireflow.ai", phone="+91-9000000008",
             designation="QA Engineer", department="Engineering",
             date_of_joining=date(2024, 1, 5), salary=95000,
             skills="Selenium, Cypress, API Testing, Python",
             bio="Quality advocate ensuring bug-free releases.",
             manager_id=mgr_emp_eng.id),
    ]

    all_employees = []
    for p in employee_profiles:
        emp = Employee(status="active", **p)
        db.add(emp)
        db.flush()
        all_employees.append(emp)

    # Link employee users to employee profiles
    for i, emp in enumerate(all_employees):
        emp_users[i].employee_id = emp.id

    all_emp_objects = [mgr_emp_eng, mgr_emp_hr, mgr_emp_sales] + all_employees

    # ── Leave Balances (2026) ──────────────────────────────────────────────
    for emp in all_emp_objects:
        for lt in ["casual", "sick", "earned"]:
            total = {"sick": 12, "casual": 12, "earned": 15}[lt]
            db.add(LeaveBalance(
                employee_id=emp.id, leave_type=lt,
                total_days=total, used_days=0, remaining_days=total, year=2026,
            ))

    # ── Sample Leave Requests ──────────────────────────────────────────────
    leaves = [
        LeaveRequest(employee_id=all_employees[0].id, leave_type="casual",
                     start_date=date(2026, 3, 20), end_date=date(2026, 3, 21),
                     reason="Family function", status="approved", approved_by=mgr_eng.id),
        LeaveRequest(employee_id=all_employees[1].id, leave_type="sick",
                     start_date=date(2026, 3, 18), end_date=date(2026, 3, 18),
                     reason="Not feeling well", status="approved", approved_by=mgr_eng.id),
        LeaveRequest(employee_id=all_employees[2].id, leave_type="casual",
                     start_date=date(2026, 3, 25), end_date=date(2026, 3, 26),
                     reason="Internet installation at new place", status="pending"),
        LeaveRequest(employee_id=all_employees[4].id, leave_type="earned",
                     start_date=date(2026, 4, 1), end_date=date(2026, 4, 5),
                     reason="Vacation trip", status="pending"),
        LeaveRequest(employee_id=all_employees[3].id, leave_type="casual",
                     start_date=date(2026, 3, 28), end_date=date(2026, 3, 28),
                     reason="Personal errand", status="pending"),
    ]
    db.add_all(leaves)

    # ── Sample Attendance (last 5 working days) ────────────────────────────
    today = date.today()
    for emp in all_emp_objects:
        for d in range(5):
            att_date = today - timedelta(days=d + 1)
            if att_date.weekday() >= 5:
                continue
            check_in_dt = datetime.combine(att_date, datetime.min.time().replace(hour=9))
            check_out_dt = datetime.combine(att_date, datetime.min.time().replace(hour=18))
            db.add(Attendance(
                employee_id=emp.id, date=att_date, status="present",
                check_in=check_in_dt, check_out=check_out_dt, work_hours=9.0,
            ))

    # ── Job Postings ───────────────────────────────────────────────────────
    job1 = JobPosting(
        title="Senior Backend Engineer",
        description="Build scalable APIs using Python/FastAPI. 3+ years experience required.",
        requirements="Python, FastAPI, Docker, PostgreSQL, 3+ years experience",
        department="Engineering", status="open", posted_by=admin_user.id,
        salary_min=120000, salary_max=180000, location="Bangalore, India",
    )
    job2 = JobPosting(
        title="Product Designer",
        description="Design intuitive interfaces for our SaaS platform.",
        requirements="Figma, UI/UX, Design Systems, User Research, 2+ years experience",
        department="Design", status="open", posted_by=admin_user.id,
        salary_min=100000, salary_max=150000, location="Remote",
    )
    job3 = JobPosting(
        title="Marketing Manager",
        description="Lead marketing campaigns and brand strategy for B2B SaaS.",
        requirements="Content Marketing, SEO, Analytics, B2B, 5+ years experience",
        department="Marketing", status="draft", posted_by=admin_user.id,
        salary_min=140000, salary_max=200000, location="Mumbai, India",
    )
    db.add_all([job1, job2, job3])
    db.flush()

    # ── Sample Candidates ──────────────────────────────────────────────────
    candidates = [
        Candidate(job_id=job1.id, name="Rajesh Khanna", email="rajesh.k@email.com",
                  phone="+91-8000000001", stage="screening", score=82.5,
                  ai_summary="Strong Python skills, API design experience. Limited Docker knowledge."),
        Candidate(job_id=job1.id, name="Fatima Ali", email="fatima.ali@email.com",
                  phone="+91-8000000002", stage="interview", score=91.0,
                  ai_summary="Full-stack experience, system design skills, FastAPI expert. No cloud cert."),
        Candidate(job_id=job2.id, name="Lisa Chen", email="lisa.chen@email.com",
                  phone="+91-8000000003", stage="applied"),
    ]
    db.add_all(candidates)

    # ── Policy Document ────────────────────────────────────────────────────
    policy_doc = Document(
        employee_id=None, document_name="Employee Handbook 2026",
        document_type="policy", file_url="/uploads/policies/handbook_2026.txt",
        is_policy=True,
        content_text="""HireFlow AI Employee Handbook 2026

LEAVE POLICY:
- Sick Leave: 12 days per year. Medical certificate required for 3+ consecutive days.
- Casual Leave: 12 days per year. Must be applied at least 1 day in advance.
- Earned Leave: 15 days per year. Can be carried forward (max 30 days). Apply 7 days in advance.
- Maternity Leave: 26 weeks as per statutory requirements.
- Paternity Leave: 2 weeks.

WORKING HOURS:
- Standard hours: 9:00 AM to 6:00 PM, Monday to Friday.
- Flexible timing allowed with core hours 10:00 AM to 4:00 PM.
- Overtime is not encouraged. Compensatory off provided for weekend work.

PROBATION:
- 6 months for all new joiners.
- Confirmation after successful completion and manager recommendation.

CODE OF CONDUCT:
- Professional behavior expected at all times.
- Zero tolerance for harassment and discrimination.
- Company property must be used responsibly.
- Confidential information must not be shared externally.

BENEFITS:
- Health insurance for employee and dependents.
- Annual performance bonus (discretionary).
- Learning and development budget: INR 50,000 per year.
- Gym/wellness reimbursement: INR 12,000 per year.

RESIGNATION AND NOTICE PERIOD:
- 30 days notice period for employees.
- 60 days notice period for managers.
- Notice period can be waived at management discretion.

WORK FROM HOME:
- Up to 2 days per week with manager approval.
- Full WFH arrangements require HR and management approval.
""",
    )
    db.add(policy_doc)

    # ── Onboarding Checklist ───────────────────────────────────────────────
    checklist = OnboardingChecklist(
        title="Software Engineer Onboarding",
        description="Standard onboarding checklist for new software engineers",
        department="Engineering",
        items=json.dumps([
            {"title": "Sign offer letter", "description": "Review and sign the offer letter", "due_days": 1, "assignee": "HR"},
            {"title": "Submit ID proof", "description": "Upload government-issued ID", "due_days": 3, "assignee": "Employee"},
            {"title": "Setup workstation", "description": "Laptop, monitor, and accessories", "due_days": 1, "assignee": "IT"},
            {"title": "Create email account", "description": "Setup company email", "due_days": 1, "assignee": "IT"},
            {"title": "Complete compliance training", "description": "Online training module", "due_days": 7, "assignee": "Employee"},
            {"title": "Meet the team", "description": "Introduction meeting with team members", "due_days": 3, "assignee": "Manager"},
        ]),
    )
    db.add(checklist)

    # ── Payroll Records (March 2026) ───────────────────────────────────────
    for emp in all_emp_objects:
        basic = emp.salary or 100000
        hra = round(basic * 0.2, 2)
        transport = 3000
        other_allow = round(basic * 0.1, 2)
        gross = basic + hra + transport + other_allow
        tax = round(gross * 0.1, 2)
        pf = round(basic * 0.12, 2)
        other_ded = 500
        net = round(gross - tax - pf - other_ded, 2)
        db.add(PayrollRecord(
            employee_id=emp.id, month=3, year=2026,
            basic_salary=basic, hra=hra, transport_allowance=transport,
            other_allowances=other_allow, gross_salary=gross,
            tax_deduction=tax, pf_deduction=pf, other_deductions=other_ded,
            net_salary=net, status="processed",
        ))

    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"message": "HireFlow AI HRMS Backend", "version": "1.0.0", "status": "running"}

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role},
    }

@app.post("/api/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=req.email, hashed_password=get_password_hash(req.password),
        full_name=req.full_name, role=req.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}

@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    emp = None
    if current_user.employee_id:
        employee = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
        if employee:
            emp = {
                "id": employee.id,
                "employee_code": employee.employee_code,
                "designation": employee.designation,
                "department": employee.department,
            }
    return {
        "id": current_user.id, "email": current_user.email,
        "full_name": current_user.full_name, "role": current_user.role,
        "employee": emp,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYEE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

def _employee_to_dict(emp: Employee) -> dict:
    return {
        "id": emp.id, "employee_code": emp.employee_code,
        "first_name": emp.first_name, "last_name": emp.last_name,
        "name": f"{emp.first_name} {emp.last_name}",
        "email": emp.email, "phone": emp.phone,
        "date_of_birth": emp.date_of_birth.isoformat() if emp.date_of_birth else None,
        "gender": emp.gender, "address": emp.address,
        "designation": emp.designation, "department": emp.department,
        "employment_type": emp.employment_type,
        "date_of_joining": emp.date_of_joining.isoformat() if emp.date_of_joining else None,
        "date_of_leaving": emp.date_of_leaving.isoformat() if emp.date_of_leaving else None,
        "manager_id": emp.manager_id, "salary": emp.salary,
        "skills": emp.skills, "bio": emp.bio,
        "status": emp.status,
        "profile_picture": emp.profile_picture,
        "created_at": emp.created_at.isoformat() if emp.created_at else None,
        "updated_at": emp.updated_at.isoformat() if emp.updated_at else None,
    }

@app.get("/api/employees")
def list_employees(
    department: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Employee)
    if department:
        q = q.filter(Employee.department == department)
    if status:
        q = q.filter(Employee.status == status)
    if search:
        q = q.filter(
            (Employee.first_name.ilike(f"%{search}%")) |
            (Employee.last_name.ilike(f"%{search}%")) |
            (Employee.email.ilike(f"%{search}%"))
        )
    total = q.count()
    employees = q.offset(skip).limit(limit).all()
    return {"total": total, "employees": [_employee_to_dict(e) for e in employees]}

@app.get("/api/employees/{employee_id}")
def get_employee(employee_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return _employee_to_dict(emp)

@app.post("/api/employees")
def create_employee(req: EmployeeCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin", "manager"))):
    if db.query(Employee).filter(Employee.employee_code == req.employee_code).first():
        raise HTTPException(status_code=400, detail="Employee code already exists")
    if db.query(Employee).filter(Employee.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    emp = Employee(**req.model_dump(), status="active")
    db.add(emp)
    db.commit()
    db.refresh(emp)
    # Create leave balances for current year
    for lt in ["casual", "sick", "earned"]:
        total = {"sick": 12, "casual": 12, "earned": 15}[lt]
        db.add(LeaveBalance(
            employee_id=emp.id, leave_type=lt,
            total_days=total, used_days=0, remaining_days=total, year=date.today().year,
        ))
    db.commit()
    return _employee_to_dict(emp)

@app.put("/api/employees/{employee_id}")
def update_employee(employee_id: int, req: EmployeeUpdate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin", "manager"))):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(emp, key, value)
    db.commit()
    db.refresh(emp)
    return _employee_to_dict(emp)

@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin"))):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    db.delete(emp)
    db.commit()
    return {"message": "Employee deleted"}

@app.post("/api/employees/{employee_id}/generate-bio")
def generate_bio(employee_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    bio = gemini.generate_employee_bio(
        f"{emp.first_name} {emp.last_name}",
        emp.designation or "",
        emp.department or "",
        emp.skills or "",
    )
    emp.bio = bio
    db.commit()
    return {"bio": bio}

@app.get("/api/employees/ai/detect-duplicates")
def detect_duplicates(db: Session = Depends(get_db),
                      current_user: User = Depends(require_role("admin", "manager"))):
    employees = db.query(Employee).all()
    data = json.dumps([{
        "employee_code": e.employee_code,
        "name": f"{e.first_name} {e.last_name}",
        "email": e.email, "phone": e.phone,
        "department": e.department, "designation": e.designation,
        "skills": e.skills,
    } for e in employees], default=str)
    result = gemini.detect_duplicate_profiles(data)
    return {"analysis": result}

@app.post("/api/employees/{employee_id}/upload-image")
async def upload_profile_image(employee_id: int, file: UploadFile = File(...),
                               db: Session = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    url = await upload_file(file, "profiles")
    emp.profile_picture = url
    db.commit()
    return {"image_url": url}


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/documents")
def list_documents(
    employee_id: Optional[int] = None, doc_type: Optional[str] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    q = db.query(Document)
    if employee_id:
        q = q.filter(Document.employee_id == employee_id)
    if doc_type:
        q = q.filter(Document.document_type == doc_type)
    docs = q.order_by(Document.uploaded_at.desc()).all()
    return [{
        "id": d.id, "employee_id": d.employee_id,
        "document_name": d.document_name, "document_type": d.document_type,
        "file_url": d.file_url, "file_size": d.file_size,
        "is_policy": d.is_policy,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
    } for d in docs]

@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    document_name: str = Form(...),
    document_type: str = Form("other"),
    employee_id: Optional[int] = Form(None),
    is_policy: bool = Form(False),
    content_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = await upload_file(file, f"documents/{document_type}")
    doc = Document(
        employee_id=employee_id, document_name=document_name,
        document_type=document_type, file_url=url,
        is_policy=is_policy, content_text=content_text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {
        "id": doc.id, "document_name": doc.document_name,
        "document_type": doc.document_type, "file_url": doc.file_url,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
    }

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin", "manager"))):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# JOB POSTING ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

def _job_to_dict(job: JobPosting, include_candidates: bool = False) -> dict:
    d = {
        "id": job.id, "title": job.title, "description": job.description,
        "requirements": job.requirements,
        "department": job.department, "location": job.location,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min, "salary_max": job.salary_max,
        "status": job.status, "posted_by": job.posted_by,
        "closing_date": job.closing_date.isoformat() if job.closing_date else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "candidate_count": len(job.candidates),
    }
    if include_candidates:
        d["candidates"] = [{
            "id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
            "stage": c.stage, "score": c.score, "ai_summary": c.ai_summary,
            "resume_url": c.resume_url,
            "applied_at": c.applied_at.isoformat() if c.applied_at else None,
        } for c in job.candidates]
    return d

@app.get("/api/jobs")
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    q = db.query(JobPosting)
    if status:
        q = q.filter(JobPosting.status == status)
    jobs = q.order_by(JobPosting.created_at.desc()).all()
    return [_job_to_dict(j) for j in jobs]

@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job, include_candidates=True)

@app.post("/api/jobs")
def create_job(req: JobPostingCreate, db: Session = Depends(get_db),
               current_user: User = Depends(require_role("admin", "manager"))):
    job = JobPosting(**req.model_dump(), posted_by=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_to_dict(job)

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, req: JobPostingCreate, db: Session = Depends(get_db),
               current_user: User = Depends(require_role("admin", "manager"))):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for key, value in req.model_dump().items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return _job_to_dict(job)

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(require_role("admin"))):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.delete(job)
    db.commit()
    return {"message": "Job deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/jobs/{job_id}/candidates")
def add_candidate(job_id: int, req: CandidateCreate, db: Session = Depends(get_db),
                  current_user: User = Depends(require_role("admin", "manager"))):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    candidate = Candidate(job_id=job_id, **req.model_dump())
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return {"id": candidate.id, "name": candidate.name, "email": candidate.email, "stage": candidate.stage}

@app.post("/api/jobs/{job_id}/candidates/{candidate_id}/upload-resume")
async def upload_resume(job_id: int, candidate_id: int, file: UploadFile = File(...),
                        db: Session = Depends(get_db),
                        current_user: User = Depends(require_role("admin", "manager"))):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id, Candidate.job_id == job_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    url = await upload_file(file, "resumes")
    candidate.resume_url = url
    db.commit()
    return {"resume_url": url}

@app.post("/api/jobs/{job_id}/candidates/{candidate_id}/score")
def score_candidate(job_id: int, candidate_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin", "manager"))):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id, Candidate.job_id == job_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    resume = candidate.resume_text or f"Candidate: {candidate.name}, Email: {candidate.email}"
    job_desc = f"{job.description}\nRequirements: {job.requirements or ''}"
    result = gemini.score_resume(resume, job_desc)
    candidate.ai_summary = result
    db.commit()
    return {"ai_summary": result}

@app.post("/api/jobs/{job_id}/candidates/{candidate_id}/questions")
def generate_questions(job_id: int, candidate_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(require_role("admin", "manager"))):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id, Candidate.job_id == job_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    resume = candidate.resume_text or f"Candidate: {candidate.name}, Email: {candidate.email}"
    job_desc = f"{job.description}\nRequirements: {job.requirements or ''}"
    questions = gemini.generate_interview_questions(job_desc, resume)
    candidate.interview_questions = questions
    db.commit()
    return {"questions": questions}

@app.put("/api/jobs/{job_id}/candidates/{candidate_id}/stage")
def update_candidate_stage(job_id: int, candidate_id: int, req: CandidateStageUpdate,
                           db: Session = Depends(get_db),
                           current_user: User = Depends(require_role("admin", "manager"))):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id, Candidate.job_id == job_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    candidate.stage = req.stage
    db.commit()
    return {"id": candidate.id, "stage": candidate.stage}


@app.get("/api/jobs/{job_id}/compare")
def compare_candidates(job_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(require_role("admin", "manager"))):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidates = db.query(Candidate).filter(Candidate.job_id == job_id).all()
    if not candidates:
        return {"candidates": [], "recommendation": "No candidates to compare yet."}

    candidates_data = json.dumps([{
        "name": c.name,
        "email": c.email,
        "stage": c.stage,
        "score": c.score,
        "summary": c.ai_summary,
    } for c in candidates], default=str)

    job_desc = f"{job.title}\n{job.description}\nRequirements: {job.requirements or ''}"
    try:
        raw = gemini.compare_candidates(candidates_data, job_desc)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        result_candidates = parsed.get("candidates") or parsed.get("comparison") or []
        recommendation = parsed.get("recommendation") or "Comparison generated."
    else:
        result_candidates = [{
            "id": c.id,
            "name": c.name,
            "score": c.score or 0,
            "strengths": [],
            "gaps": [],
        } for c in candidates]
        recommendation = "AI comparison unavailable; showing basic candidate data."

    return {"candidates": result_candidates, "recommendation": recommendation}


# ═══════════════════════════════════════════════════════════════════════════════
# LEAVE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/leaves")
def list_leaves(
    employee_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(LeaveRequest)
    if employee_id:
        q = q.filter(LeaveRequest.employee_id == employee_id)
    if status_filter:
        q = q.filter(LeaveRequest.status == status_filter)
    leaves = q.order_by(LeaveRequest.created_at.desc()).all()
    result = []
    for lr in leaves:
        emp = db.query(Employee).filter(Employee.id == lr.employee_id).first()
        result.append({
            "id": lr.id, "employee_id": lr.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "Unknown",
            "leave_type": lr.leave_type,
            "start_date": lr.start_date.isoformat(),
            "end_date": lr.end_date.isoformat(),
            "reason": lr.reason, "status": lr.status,
            "comments": lr.comments, "approved_by": lr.approved_by,
            "created_at": lr.created_at.isoformat() if lr.created_at else None,
        })
    return result

@app.post("/api/leaves")
def create_leave(req: LeaveRequestCreate, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    if not current_user.employee_id:
        raise HTTPException(status_code=400, detail="No employee profile linked to your account")
    emp = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
    if not emp:
        raise HTTPException(status_code=400, detail="Employee profile not found")
    if req.end_date < req.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")
    leave = LeaveRequest(
        employee_id=emp.id, leave_type=req.leave_type,
        start_date=req.start_date, end_date=req.end_date, reason=req.reason,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return {"id": leave.id, "status": leave.status, "message": "Leave request submitted"}

@app.put("/api/leaves/{leave_id}/action")
def action_leave(leave_id: int, req: LeaveActionRequest, db: Session = Depends(get_db),
                 current_user: User = Depends(require_role("admin", "manager"))):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="Leave already processed")
    leave.status = req.action
    leave.comments = req.comments
    leave.approved_by = current_user.id
    # Update leave balance if approved
    if req.action == "approved":
        days = (leave.end_date - leave.start_date).days + 1
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == leave.employee_id,
            LeaveBalance.leave_type == leave.leave_type,
            LeaveBalance.year == leave.start_date.year,
        ).first()
        if balance:
            balance.used_days += days
            balance.remaining_days = balance.total_days - balance.used_days
    db.commit()
    return {"id": leave.id, "status": leave.status}

@app.get("/api/leaves/balance/{employee_id}")
def get_leave_balance(employee_id: int, year: int = Query(default=2026),
                      db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    balances = db.query(LeaveBalance).filter(
        LeaveBalance.employee_id == employee_id, LeaveBalance.year == year
    ).all()
    return [{
        "leave_type": b.leave_type, "total_days": b.total_days,
        "used_days": b.used_days, "remaining_days": b.remaining_days,
    } for b in balances]

@app.get("/api/leaves/ai/analyze")
def analyze_leaves(db: Session = Depends(get_db),
                   current_user: User = Depends(require_role("admin", "manager"))):
    leaves = db.query(LeaveRequest).all()
    leave_data = []
    for lr in leaves:
        emp = db.query(Employee).filter(Employee.id == lr.employee_id).first()
        leave_data.append({
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "Unknown",
            "department": emp.department if emp else "N/A",
            "leave_type": lr.leave_type,
            "start_date": lr.start_date.isoformat(),
            "end_date": lr.end_date.isoformat(),
            "status": lr.status,
            "day_of_week": lr.start_date.strftime("%A"),
        })
    result = gemini.analyze_leave_patterns(json.dumps(leave_data, default=str))
    return {"analysis": result}


# ═══════════════════════════════════════════════════════════════════════════════
# ATTENDANCE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/attendance")
def list_attendance(
    employee_id: Optional[int] = None,
    from_date: Optional[date] = None, to_date: Optional[date] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    q = db.query(Attendance)
    if employee_id:
        q = q.filter(Attendance.employee_id == employee_id)
    if from_date:
        q = q.filter(Attendance.date >= from_date)
    if to_date:
        q = q.filter(Attendance.date <= to_date)
    records = q.order_by(Attendance.date.desc()).all()
    return [{
        "id": a.id, "employee_id": a.employee_id, "date": a.date.isoformat(),
        "status": a.status, "work_hours": a.work_hours, "notes": a.notes,
        "check_in": a.check_in.isoformat() if a.check_in else None,
        "check_out": a.check_out.isoformat() if a.check_out else None,
    } for a in records]

@app.post("/api/attendance")
def mark_attendance(req: AttendanceCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    if not current_user.employee_id:
        raise HTTPException(status_code=400, detail="No employee profile linked")
    emp = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
    if not emp:
        raise HTTPException(status_code=400, detail="Employee profile not found")
    existing = db.query(Attendance).filter(
        Attendance.employee_id == emp.id, Attendance.date == req.date
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Attendance already marked for this date")
    check_in_dt = datetime.fromisoformat(req.check_in) if req.check_in else None
    check_out_dt = datetime.fromisoformat(req.check_out) if req.check_out else None
    work_hours = 0
    if check_in_dt and check_out_dt:
        work_hours = round((check_out_dt - check_in_dt).total_seconds() / 3600, 2)
    att = Attendance(
        employee_id=emp.id, date=req.date, status=req.status,
        check_in=check_in_dt, check_out=check_out_dt,
        work_hours=work_hours, notes=req.notes,
    )
    db.add(att)
    db.commit()
    return {"id": att.id, "date": att.date.isoformat(), "status": att.status}

@app.post("/api/attendance/bulk")
def bulk_attendance(
    records: List[dict],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    created = 0
    for rec in records:
        emp_id = rec.get("employee_id")
        att_date = date.fromisoformat(rec.get("date"))
        existing = db.query(Attendance).filter(
            Attendance.employee_id == emp_id, Attendance.date == att_date
        ).first()
        if not existing:
            check_in = datetime.fromisoformat(rec["check_in"]) if rec.get("check_in") else None
            check_out = datetime.fromisoformat(rec["check_out"]) if rec.get("check_out") else None
            work_hours = 0
            if check_in and check_out:
                work_hours = round((check_out - check_in).total_seconds() / 3600, 2)
            att = Attendance(
                employee_id=emp_id, date=att_date,
                status=rec.get("status", "present"),
                check_in=check_in, check_out=check_out,
                work_hours=work_hours,
            )
            db.add(att)
            created += 1
    db.commit()
    return {"created": created}


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE REVIEW ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/reviews/cycles")
def list_review_cycles(db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    cycles = db.query(ReviewCycle).order_by(ReviewCycle.created_at.desc()).all()
    return [{
        "id": c.id, "name": c.name, "description": c.description,
        "start_date": c.start_date.isoformat(), "end_date": c.end_date.isoformat(),
        "status": c.status, "review_count": len(c.reviews),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in cycles]

@app.post("/api/reviews/cycles")
def create_review_cycle(req: ReviewCycleCreate, db: Session = Depends(get_db),
                        current_user: User = Depends(require_role("admin", "manager"))):
    cycle = ReviewCycle(
        name=req.name, description=req.description,
        start_date=req.start_date, end_date=req.end_date,
        status="draft",
    )
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return {"id": cycle.id, "name": cycle.name, "status": cycle.status}

@app.post("/api/reviews/cycles/{cycle_id}/activate")
def activate_review_cycle(cycle_id: int, db: Session = Depends(get_db),
                          current_user: User = Depends(require_role("admin", "manager"))):
    cycle = db.query(ReviewCycle).filter(ReviewCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    cycle.status = "active"
    employees = db.query(Employee).filter(Employee.status == "active").all()
    count = 0
    for emp in employees:
        existing = db.query(PerformanceReview).filter(
            PerformanceReview.cycle_id == cycle_id, PerformanceReview.employee_id == emp.id
        ).first()
        if not existing:
            db.add(PerformanceReview(cycle_id=cycle_id, employee_id=emp.id, status="pending"))
            count += 1
    db.commit()
    return {"message": f"Cycle activated with {count} reviews created"}

@app.get("/api/reviews/cycles/{cycle_id}/reviews")
def list_reviews_for_cycle(cycle_id: int, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    reviews = db.query(PerformanceReview).filter(PerformanceReview.cycle_id == cycle_id).all()
    result = []
    for r in reviews:
        emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
        ai_summary_value = r.ai_summary
        if isinstance(ai_summary_value, str) and ai_summary_value.strip():
            try:
                ai_summary_value = json.loads(ai_summary_value)
            except json.JSONDecodeError:
                ai_summary_value = {
                    "summary": ai_summary_value,
                    "flags": [],
                    "suggestions": [],
                }
        result.append({
            "id": r.id, "cycle_id": r.cycle_id, "employee_id": r.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "Unknown",
            "department": emp.department if emp else "N/A",
            "self_rating": r.self_rating, "self_comments": r.self_comments,
            "manager_rating": r.manager_rating, "manager_comments": r.manager_comments,
            "goals": r.goals, "achievements": r.achievements,
            "areas_of_improvement": r.areas_of_improvement,
            "overall_rating": r.overall_rating,
            "ai_summary": ai_summary_value, "status": r.status,
        })
    return result

@app.post("/api/reviews/{review_id}/self-assessment")
def submit_self_assessment(review_id: int, req: SelfAssessmentSubmit,
                           db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.self_rating = req.self_rating
    review.self_comments = req.self_comments
    review.achievements = req.achievements
    review.goals = req.goals
    review.status = "self_review"
    db.commit()
    return {"message": "Self-assessment submitted"}

@app.post("/api/reviews/{review_id}/manager-review")
def submit_manager_review(review_id: int, req: ManagerReviewSubmit,
                          db: Session = Depends(get_db),
                          current_user: User = Depends(require_role("admin", "manager"))):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.manager_rating = req.manager_rating
    review.manager_comments = req.manager_comments
    review.areas_of_improvement = req.areas_of_improvement
    review.overall_rating = round((review.self_rating + req.manager_rating) / 2, 2) if review.self_rating else req.manager_rating
    review.status = "completed"
    # Link reviewer
    if current_user.employee_id:
        review.reviewer_id = current_user.employee_id
    # Generate AI summary
    try:
        emp = db.query(Employee).filter(Employee.id == review.employee_id).first()
        review_data = json.dumps({
            "employee": f"{emp.first_name} {emp.last_name}" if emp else "Employee",
            "self_rating": review.self_rating,
            "self_comments": review.self_comments,
            "achievements": review.achievements,
            "goals": review.goals,
            "manager_rating": req.manager_rating,
            "manager_comments": req.manager_comments,
            "areas_of_improvement": req.areas_of_improvement,
            "overall_rating": review.overall_rating,
        })
        review.ai_summary = gemini.generate_review_summary(review_data)
    except Exception:
        review.ai_summary = "AI summary generation failed. Please review manually."
    db.commit()
    return {"message": "Manager review submitted", "ai_summary": review.ai_summary}


@app.post("/api/reviews/{review_id}/generate-summary")
def generate_review_summary_endpoint(review_id: int, db: Session = Depends(get_db),
                                     current_user: User = Depends(require_role("admin", "manager"))):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    emp = db.query(Employee).filter(Employee.id == review.employee_id).first()
    review_data = json.dumps({
        "employee": f"{emp.first_name} {emp.last_name}" if emp else "Employee",
        "self_rating": review.self_rating,
        "self_comments": review.self_comments,
        "achievements": review.achievements,
        "goals": review.goals,
        "manager_rating": review.manager_rating,
        "manager_comments": review.manager_comments,
        "areas_of_improvement": review.areas_of_improvement,
        "overall_rating": review.overall_rating,
    })

    try:
        raw = gemini.generate_review_summary(review_data)
    except Exception:
        raw = "Performance is stable overall. Continue with focused growth actions."

    payload = None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = {
                    "summary": parsed.get("summary") or raw,
                    "flags": parsed.get("flags") or [],
                    "suggestions": parsed.get("suggestions") or parsed.get("recommendations") or [],
                }
        except json.JSONDecodeError:
            pass

    if payload is None:
        payload = {
            "summary": raw if isinstance(raw, str) else "Summary generated.",
            "flags": [],
            "suggestions": [],
        }

    review.ai_summary = json.dumps(payload)
    db.commit()
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/onboarding/checklists")
def list_checklists(db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    checklists = db.query(OnboardingChecklist).all()
    return [{
        "id": c.id, "title": c.title, "description": c.description,
        "department": c.department, "items": c.items,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in checklists]

@app.post("/api/onboarding/checklists")
def create_checklist(req: OnboardingChecklistCreate, db: Session = Depends(get_db),
                     current_user: User = Depends(require_role("admin", "manager"))):
    cl = OnboardingChecklist(
        title=req.title, description=req.description,
        department=req.department, items=req.items,
    )
    db.add(cl)
    db.commit()
    db.refresh(cl)
    return {"id": cl.id, "title": cl.title, "items": cl.items}

@app.post("/api/onboarding/assign/{employee_id}/{checklist_id}")
def assign_onboarding(employee_id: int, checklist_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(require_role("admin", "manager"))):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    cl = db.query(OnboardingChecklist).filter(OnboardingChecklist.id == checklist_id).first()
    if not emp or not cl:
        raise HTTPException(status_code=404, detail="Employee or checklist not found")
    progress = OnboardingProgress(
        employee_id=employee_id, checklist_id=checklist_id,
        completed_items="", status="in_progress",
    )
    db.add(progress)
    db.commit()
    db.refresh(progress)
    return {"id": progress.id, "status": progress.status}

@app.get("/api/onboarding/progress/{employee_id}")
def get_onboarding_progress(employee_id: int, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    records = db.query(OnboardingProgress).filter(OnboardingProgress.employee_id == employee_id).all()
    result = []
    for p in records:
        cl = db.query(OnboardingChecklist).filter(OnboardingChecklist.id == p.checklist_id).first()
        result.append({
            "id": p.id, "checklist_id": p.checklist_id,
            "title": cl.title if cl else "Unknown",
            "items": cl.items if cl else "[]",
            "completed_items": p.completed_items or "",
            "status": p.status,
            "started_at": p.started_at.isoformat() if p.started_at else None,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        })
    return result

@app.put("/api/onboarding/progress/{progress_id}")
def update_onboarding_progress(progress_id: int, req: ChecklistProgressUpdate,
                               db: Session = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    progress = db.query(OnboardingProgress).filter(OnboardingProgress.id == progress_id).first()
    if not progress:
        raise HTTPException(status_code=404, detail="Progress record not found")
    progress.completed_items = req.completed_items
    # Check completion
    cl = db.query(OnboardingChecklist).filter(OnboardingChecklist.id == progress.checklist_id).first()
    if cl and cl.items:
        try:
            items_list = json.loads(cl.items) if isinstance(cl.items, str) else cl.items
            completed_indices = [int(x.strip()) for x in req.completed_items.split(",") if x.strip()] if req.completed_items else []
            if len(completed_indices) >= len(items_list):
                progress.status = "completed"
                progress.completed_at = datetime.utcnow()
        except (json.JSONDecodeError, ValueError):
            pass
    db.commit()
    return {"status": progress.status, "completed_items": progress.completed_items}


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT / POLICY BOT ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
def chat_with_hr(req: ChatRequest, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    # Gather policy documents
    policy_docs = db.query(Document).filter(Document.is_policy == True).all()
    policy_context = ""
    for doc in policy_docs:
        if doc.content_text:
            policy_context += doc.content_text + "\n\n"
    if not policy_context:
        policy_context = """HireFlow AI Employee Handbook 2026

LEAVE POLICY:
- Sick Leave: 12 days per year. Medical certificate required for 3+ consecutive days.
- Casual Leave: 12 days per year. Must be applied at least 1 day in advance.
- Earned Leave: 15 days per year. Can be carried forward (max 30 days). Apply 7 days in advance.

WORKING HOURS:
- Standard hours: 9:00 AM to 6:00 PM, Monday to Friday.
- Flexible timing allowed with core hours 10:00 AM to 4:00 PM.

BENEFITS:
- Health insurance for employee and dependents.
- Annual performance bonus (discretionary).
- Learning and development budget: INR 50,000 per year.
"""

    response_text = gemini.answer_policy_question(req.message, policy_context)

    # Save chat message
    if current_user.employee_id:
        emp = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
        if emp:
            msg = ChatMessage(employee_id=emp.id, message=req.message, response=response_text)
            db.add(msg)
            db.commit()
    return {"response": response_text}

@app.get("/api/chat/history")
def chat_history(db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    if not current_user.employee_id:
        return []
    emp = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
    if not emp:
        return []
    messages = db.query(ChatMessage).filter(ChatMessage.employee_id == emp.id)\
        .order_by(ChatMessage.created_at.desc()).limit(50).all()
    return [{"id": m.id, "message": m.message, "response": m.response,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in messages]


@app.get("/api/chat/frequent-questions")
def frequent_questions(db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    if not current_user.employee_id:
        return []
    rows = db.query(
        ChatMessage.message,
        func.count(ChatMessage.id).label("count")
    ).filter(
        ChatMessage.employee_id == current_user.employee_id
    ).group_by(
        ChatMessage.message
    ).order_by(
        func.count(ChatMessage.id).desc()
    ).limit(10).all()
    return [{"question": r[0], "count": r[1]} for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# PAYROLL ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/payroll")
def list_payroll(
    employee_id: Optional[int] = None, month: Optional[int] = None, year: Optional[int] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    q = db.query(PayrollRecord)
    if employee_id:
        q = q.filter(PayrollRecord.employee_id == employee_id)
    if month:
        q = q.filter(PayrollRecord.month == month)
    if year:
        q = q.filter(PayrollRecord.year == year)
    records = q.order_by(PayrollRecord.year.desc(), PayrollRecord.month.desc()).all()
    result = []
    for r in records:
        emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
        result.append({
            "id": r.id, "employee_id": r.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "Unknown",
            "month": r.month, "year": r.year,
            "basic_salary": r.basic_salary, "hra": r.hra,
            "transport_allowance": r.transport_allowance,
            "other_allowances": r.other_allowances,
            "gross_salary": r.gross_salary,
            "tax_deduction": r.tax_deduction, "pf_deduction": r.pf_deduction,
            "other_deductions": r.other_deductions,
            "net_salary": r.net_salary, "status": r.status,
        })
    return result

@app.post("/api/payroll")
def create_payroll(req: PayrollCreate, db: Session = Depends(get_db),
                   current_user: User = Depends(require_role("admin"))):
    existing = db.query(PayrollRecord).filter(
        PayrollRecord.employee_id == req.employee_id,
        PayrollRecord.month == req.month, PayrollRecord.year == req.year,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Payroll record already exists for this period")
    gross = req.basic_salary + req.hra + req.transport_allowance + req.other_allowances
    total_deductions = req.tax_deduction + req.pf_deduction + req.other_deductions
    net = gross - total_deductions
    record = PayrollRecord(
        employee_id=req.employee_id, month=req.month, year=req.year,
        basic_salary=req.basic_salary, hra=req.hra,
        transport_allowance=req.transport_allowance,
        other_allowances=req.other_allowances, gross_salary=gross,
        tax_deduction=req.tax_deduction, pf_deduction=req.pf_deduction,
        other_deductions=req.other_deductions, net_salary=net,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "net_salary": record.net_salary, "status": record.status}

@app.put("/api/payroll/{record_id}/process")
def process_payroll(record_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin"))):
    record = db.query(PayrollRecord).filter(PayrollRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Payroll record not found")
    record.status = "processed"
    db.commit()
    return {"id": record.id, "status": record.status}

@app.put("/api/payroll/{record_id}/pay")
def mark_paid(record_id: int, db: Session = Depends(get_db),
              current_user: User = Depends(require_role("admin"))):
    record = db.query(PayrollRecord).filter(PayrollRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Payroll record not found")
    record.status = "paid"
    record.paid_at = datetime.utcnow()
    db.commit()
    return {"id": record.id, "status": record.status}


# ═══════════════════════════════════════════════════════════════════════════════
# AI / ANALYTICS ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/ai/offer-letter")
def generate_offer_letter_endpoint(req: OfferLetterRequest,
                                   current_user: User = Depends(require_role("admin", "manager"))):
    letter = gemini.generate_offer_letter(
        req.employee_name, req.designation, req.department, req.salary, req.joining_date,
    )
    return {"offer_letter": letter}

@app.get("/api/ai/capacity-risk/{department}")
def get_capacity_risk(department: str, db: Session = Depends(get_db),
                      current_user: User = Depends(require_role("admin", "manager"))):
    employees = db.query(Employee).filter(
        Employee.department == department, Employee.status == "active"
    ).all()
    emp_ids = [e.id for e in employees]
    upcoming_leaves = db.query(LeaveRequest).filter(
        LeaveRequest.employee_id.in_(emp_ids),
        LeaveRequest.status.in_(["approved", "pending"]),
        LeaveRequest.start_date >= date.today(),
    ).all()
    attendance = db.query(Attendance).filter(
        Attendance.employee_id.in_(emp_ids),
        Attendance.date >= date.today() - timedelta(days=30),
    ).all()
    leave_str = json.dumps([{
        "employee": f"{db.query(Employee).get(lr.employee_id).first_name} {db.query(Employee).get(lr.employee_id).last_name}" if db.query(Employee).get(lr.employee_id) else "Unknown",
        "start": lr.start_date.isoformat(), "end": lr.end_date.isoformat(),
        "type": lr.leave_type, "status": lr.status,
    } for lr in upcoming_leaves], default=str)
    att_str = json.dumps([{
        "employee_id": a.employee_id, "date": a.date.isoformat(), "status": a.status,
    } for a in attendance], default=str)
    result = gemini.predict_team_capacity(att_str, leave_str)
    return {"analysis": result, "team_size": len(employees)}

@app.get("/api/analytics/dashboard")
def get_dashboard_analytics(db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    total_employees = db.query(Employee).filter(Employee.status == "active").count()
    departments = db.query(Employee.department, func.count(Employee.id))\
        .filter(Employee.status == "active")\
        .group_by(Employee.department).all()
    pending_leaves = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").count()
    open_jobs = db.query(JobPosting).filter(JobPosting.status == "open").count()
    total_candidates = db.query(Candidate).count()
    today = date.today()
    present_today = db.query(Attendance).filter(Attendance.date == today).count()
    return {
        "total_employees": total_employees,
        "departments": [{"name": d[0] or "Unassigned", "count": d[1]} for d in departments],
        "pending_leaves": pending_leaves,
        "open_positions": open_jobs,
        "total_candidates": total_candidates,
        "present_today": present_today,
    }

@app.get("/api/analytics/hr-summary")
def get_hr_summary(db: Session = Depends(get_db),
                   current_user: User = Depends(require_role("admin", "manager"))):
    total_employees = db.query(Employee).filter(Employee.status == "active").count()
    departments = db.query(Employee.department, func.count(Employee.id))\
        .filter(Employee.status == "active")\
        .group_by(Employee.department).all()
    pending_leaves = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").count()
    approved_leaves = db.query(LeaveRequest).filter(LeaveRequest.status == "approved").count()
    open_jobs = db.query(JobPosting).filter(JobPosting.status == "open").count()
    total_candidates = db.query(Candidate).count()
    hired = db.query(Candidate).filter(Candidate.stage == "hired").count()

    analytics_data = json.dumps({
        "total_active_employees": total_employees,
        "department_distribution": {d[0]: d[1] for d in departments},
        "leave_stats": {"pending": pending_leaves, "approved_this_month": approved_leaves},
        "recruitment": {"open_positions": open_jobs, "total_candidates": total_candidates, "hired": hired},
    }, default=str)
    summary = gemini.generate_hr_summary(analytics_data)
    return {"summary": summary, "data": json.loads(analytics_data)}


# ═══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT (Admin)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/users")
def list_users(db: Session = Depends(get_db),
               current_user: User = Depends(require_role("admin"))):
    users = db.query(User).all()
    return [{
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role, "is_active": u.is_active,
        "employee_id": u.employee_id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]

@app.put("/api/users/{user_id}/role")
def update_user_role(user_id: int, role: str = Query(...),
                     db: Session = Depends(get_db),
                     current_user: User = Depends(require_role("admin"))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    db.commit()
    return {"id": user.id, "role": user.role}

@app.put("/api/users/{user_id}/deactivate")
def deactivate_user(user_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_role("admin"))):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    return {"id": user.id, "is_active": user.is_active}

@app.put("/api/users/{user_id}/link-employee/{employee_id}")
def link_user_to_employee(user_id: int, employee_id: int, db: Session = Depends(get_db),
                          current_user: User = Depends(require_role("admin"))):
    user = db.query(User).filter(User.id == user_id).first()
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not user or not emp:
        raise HTTPException(status_code=404, detail="User or Employee not found")
    user.employee_id = employee_id
    db.commit()
    return {"id": user.id, "employee_id": user.employee_id}


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
