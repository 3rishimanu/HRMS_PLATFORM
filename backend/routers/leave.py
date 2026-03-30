from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

from database import get_db
from models.models import LeaveRequest, LeaveBalance, Employee, User
from services.auth import get_current_user
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/leaves", tags=["Leave Management"])


# ---------- Schemas ----------

class LeaveApply(BaseModel):
    employee_id: int
    leave_type: str
    start_date: date
    end_date: date
    reason: Optional[str] = None


class LeaveActionRequest(BaseModel):
    comments: Optional[str] = None


class LeaveResponse(BaseModel):
    id: int
    employee_id: int
    leave_type: str
    start_date: date
    end_date: date
    reason: Optional[str] = None
    status: Optional[str] = None
    approved_by: Optional[int] = None
    comments: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeaveBalanceResponse(BaseModel):
    id: int
    employee_id: int
    leave_type: str
    total_days: float
    used_days: float
    remaining_days: float
    year: int

    class Config:
        from_attributes = True


# ---------- Routes ----------

@router.get("", response_model=List[LeaveResponse])
def list_leaves(
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    leave_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(LeaveRequest)
    if employee_id:
        query = query.filter(LeaveRequest.employee_id == employee_id)
    if status:
        query = query.filter(LeaveRequest.status == status)
    if leave_type:
        query = query.filter(LeaveRequest.leave_type == leave_type)
    leaves = query.order_by(LeaveRequest.created_at.desc()).offset(skip).limit(limit).all()
    return [LeaveResponse.model_validate(l) for l in leaves]


@router.post("", response_model=LeaveResponse, status_code=status.HTTP_201_CREATED)
def apply_leave(
    payload: LeaveApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    days_requested = (payload.end_date - payload.start_date).days + 1

    balance = (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == payload.employee_id,
            LeaveBalance.leave_type == payload.leave_type,
            LeaveBalance.year == payload.start_date.year,
        )
        .first()
    )
    if balance and balance.remaining_days < days_requested:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient leave balance. Available: {balance.remaining_days}, Requested: {days_requested}",
        )

    leave = LeaveRequest(
        employee_id=payload.employee_id,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return LeaveResponse.model_validate(leave)


@router.put("/{leave_id}/approve", response_model=LeaveResponse)
def approve_leave(
    leave_id: int,
    payload: LeaveActionRequest = LeaveActionRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail=f"Leave is already {leave.status}")

    leave.status = "approved"
    leave.approved_by = current_user.id
    leave.comments = payload.comments

    days_used = (leave.end_date - leave.start_date).days + 1
    balance = (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.employee_id == leave.employee_id,
            LeaveBalance.leave_type == leave.leave_type,
            LeaveBalance.year == leave.start_date.year,
        )
        .first()
    )
    if balance:
        balance.used_days += days_used
        balance.remaining_days = balance.total_days - balance.used_days

    db.commit()
    db.refresh(leave)
    return LeaveResponse.model_validate(leave)


@router.put("/{leave_id}/reject", response_model=LeaveResponse)
def reject_leave(
    leave_id: int,
    payload: LeaveActionRequest = LeaveActionRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail=f"Leave is already {leave.status}")

    leave.status = "rejected"
    leave.approved_by = current_user.id
    leave.comments = payload.comments
    db.commit()
    db.refresh(leave)
    return LeaveResponse.model_validate(leave)


@router.get("/balance/{employee_id}", response_model=List[LeaveBalanceResponse])
def get_leave_balance(
    employee_id: int,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    query = db.query(LeaveBalance).filter(LeaveBalance.employee_id == employee_id)
    if year:
        query = query.filter(LeaveBalance.year == year)
    else:
        query = query.filter(LeaveBalance.year == date.today().year)
    balances = query.all()
    return [LeaveBalanceResponse.model_validate(b) for b in balances]


@router.get("/team-calendar")
def get_team_calendar(
    month: Optional[int] = None,
    year: Optional[int] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    query = (
        db.query(LeaveRequest, Employee)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(
            LeaveRequest.status == "approved",
            extract("month", LeaveRequest.start_date) <= target_month,
            extract("month", LeaveRequest.end_date) >= target_month,
            extract("year", LeaveRequest.start_date) <= target_year,
            extract("year", LeaveRequest.end_date) >= target_year,
        )
    )
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    results = query.all()
    calendar_data = []
    for leave, emp in results:
        calendar_data.append({
            "employee_id": emp.id,
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "department": emp.department,
            "leave_type": leave.leave_type,
            "start_date": leave.start_date.isoformat(),
            "end_date": leave.end_date.isoformat(),
        })
    return {"month": target_month, "year": target_year, "leaves": calendar_data}


@router.post("/analyze-patterns")
def analyze_leave_patterns(
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(LeaveRequest, Employee)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
    )
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))

    results = query.all()
    leave_lines = []
    for leave, emp in results:
        leave_lines.append(
            f"Employee: {emp.first_name} {emp.last_name} | Dept: {emp.department} | "
            f"Type: {leave.leave_type} | From: {leave.start_date} | To: {leave.end_date} | "
            f"Status: {leave.status}"
        )

    ai = GeminiService()
    analysis = ai.analyze_leave_patterns("\n".join(leave_lines))
    return {"analysis": analysis}
