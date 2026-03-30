from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, Date, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    hr = "hr"
    manager = "manager"
    employee = "employee"


class EmployeeStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    on_leave = "on_leave"


class DocType(str, enum.Enum):
    resume = "resume"
    id_proof = "id_proof"
    offer_letter = "offer_letter"
    policy = "policy"
    other = "other"


class JobStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    on_hold = "on_hold"
    draft = "draft"


class CandidateStage(str, enum.Enum):
    applied = "applied"
    screening = "screening"
    interview = "interview"
    shortlisted = "shortlisted"
    offered = "offered"
    hired = "hired"
    rejected = "rejected"


class LeaveType(str, enum.Enum):
    casual = "casual"
    sick = "sick"
    earned = "earned"
    maternity = "maternity"
    paternity = "paternity"
    unpaid = "unpaid"


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent = "absent"
    half_day = "half_day"
    work_from_home = "work_from_home"
    on_leave = "on_leave"


class ReviewCycleStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    draft = "draft"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    self_review = "self_review"
    manager_review = "manager_review"
    completed = "completed"


class OnboardingStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"
    overdue = "overdue"


class PayrollStatus(str, enum.Enum):
    draft = "draft"
    processed = "processed"
    paid = "paid"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), default="employee")
    is_active = Column(Boolean, default=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="user", foreign_keys=[employee_id])


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_code = Column(String(50), unique=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20))
    date_of_birth = Column(Date)
    gender = Column(String(20))
    address = Column(Text)
    department = Column(String(100))
    designation = Column(String(100))
    employment_type = Column(String(50), default="full-time")
    date_of_joining = Column(Date)
    date_of_leaving = Column(Date, nullable=True)
    status = Column(String(20), default="active")
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    salary = Column(Float, default=0)
    skills = Column(Text)
    bio = Column(Text)
    profile_picture = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    manager = relationship("Employee", remote_side=[id], backref="direct_reports")
    user = relationship("User", back_populates="employee", foreign_keys=[User.employee_id])
    documents = relationship("Document", back_populates="employee")
    leave_requests = relationship("LeaveRequest", back_populates="employee")
    leave_balances = relationship("LeaveBalance", back_populates="employee")
    attendance_records = relationship("Attendance", back_populates="employee")
    performance_reviews = relationship("PerformanceReview", back_populates="employee", foreign_keys="[PerformanceReview.employee_id]")
    onboarding_progress = relationship("OnboardingProgress", back_populates="employee")
    chat_messages = relationship("ChatMessage", back_populates="employee")
    payroll_records = relationship("PayrollRecord", back_populates="employee")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    document_name = Column(String(255), nullable=False)
    document_type = Column(String(100))
    file_url = Column(String(500))
    file_size = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    is_policy = Column(Boolean, default=False)
    content_text = Column(Text)

    employee = relationship("Employee", back_populates="documents")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    department = Column(String(100))
    description = Column(Text)
    requirements = Column(Text)
    location = Column(String(255))
    employment_type = Column(String(50), default="full-time")
    salary_min = Column(Float)
    salary_max = Column(Float)
    status = Column(String(50), default="open")
    posted_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closing_date = Column(Date, nullable=True)

    candidates = relationship("Candidate", back_populates="job")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(20))
    resume_url = Column(String(500))
    resume_text = Column(Text)
    cover_letter = Column(Text)
    stage = Column(String(50), default="applied")
    score = Column(Float, nullable=True)
    ai_summary = Column(Text)
    interview_questions = Column(Text)
    applied_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("JobPosting", back_populates="candidates")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    leave_type = Column(String(50), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(Text)
    status = Column(String(20), default="pending")
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    comments = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="leave_requests")


class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    leave_type = Column(String(50), nullable=False)
    total_days = Column(Float, default=0)
    used_days = Column(Float, default=0)
    remaining_days = Column(Float, default=0)
    year = Column(Integer, nullable=False)

    employee = relationship("Employee", back_populates="leave_balances")


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    date = Column(Date, nullable=False)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    status = Column(String(20), default="present")
    work_hours = Column(Float, default=0)
    notes = Column(Text)

    employee = relationship("Employee", back_populates="attendance_records")


class ReviewCycle(Base):
    __tablename__ = "review_cycles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

    reviews = relationship("PerformanceReview", back_populates="cycle")


class PerformanceReview(Base):
    __tablename__ = "performance_reviews"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("review_cycles.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    self_rating = Column(Float, nullable=True)
    self_comments = Column(Text)
    manager_rating = Column(Float, nullable=True)
    manager_comments = Column(Text)
    goals = Column(Text)
    achievements = Column(Text)
    areas_of_improvement = Column(Text)
    overall_rating = Column(Float, nullable=True)
    ai_summary = Column(Text)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cycle = relationship("ReviewCycle", back_populates="reviews")
    employee = relationship("Employee", back_populates="performance_reviews", foreign_keys=[employee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewer_id])


class OnboardingChecklist(Base):
    __tablename__ = "onboarding_checklists"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    department = Column(String(100))
    items = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    progress_records = relationship("OnboardingProgress", back_populates="checklist")


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    checklist_id = Column(Integer, ForeignKey("onboarding_checklists.id"), nullable=False)
    completed_items = Column(Text, default="")
    status = Column(String(50), default="in_progress")
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    employee = relationship("Employee", back_populates="onboarding_progress")
    checklist = relationship("OnboardingChecklist", back_populates="progress_records")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text)
    message_type = Column(String(20), default="question")
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="chat_messages")


class PayrollRecord(Base):
    __tablename__ = "payroll_records"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    basic_salary = Column(Float, default=0)
    hra = Column(Float, default=0)
    transport_allowance = Column(Float, default=0)
    other_allowances = Column(Float, default=0)
    gross_salary = Column(Float, default=0)
    tax_deduction = Column(Float, default=0)
    pf_deduction = Column(Float, default=0)
    other_deductions = Column(Float, default=0)
    net_salary = Column(Float, default=0)
    status = Column(String(50), default="draft")
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="payroll_records")
