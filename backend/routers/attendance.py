from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

from database import get_db
from models.models import Attendance, Employee, LeaveRequest, User
from services.auth import get_current_user
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])


# ---------- Schemas ----------

class AttendanceMark(BaseModel):
    employee_id: int
    date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    status: Optional[str] = "present"
    notes: Optional[str] = None


class AttendanceResponse(BaseModel):
    id: int
    employee_id: int
    date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    status: Optional[str] = None
    work_hours: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class AttendanceSummary(BaseModel):
    employee_id: int
    employee_name: str
    month: int
    year: int
    total_days: int
    present_days: int
    absent_days: int
    half_days: int
    wfh_days: int
    leave_days: int
    avg_work_hours: float


# ---------- Routes ----------

@router.post("", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED)
def mark_attendance(
    payload: AttendanceMark,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    existing = (
        db.query(Attendance)
        .filter(Attendance.employee_id == payload.employee_id, Attendance.date == payload.date)
        .first()
    )
    if existing:
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(existing, key, value)
        if existing.check_in and existing.check_out:
            delta = existing.check_out - existing.check_in
            existing.work_hours = round(delta.total_seconds() / 3600, 2)
        db.commit()
        db.refresh(existing)
        return AttendanceResponse.model_validate(existing)

    work_hours = 0.0
    if payload.check_in and payload.check_out:
        delta = payload.check_out - payload.check_in
        work_hours = round(delta.total_seconds() / 3600, 2)

    att = Attendance(
        employee_id=payload.employee_id,
        date=payload.date,
        check_in=payload.check_in,
        check_out=payload.check_out,
        status=payload.status,
        work_hours=work_hours,
        notes=payload.notes,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return AttendanceResponse.model_validate(att)


@router.get("", response_model=List[AttendanceResponse])
def list_attendance(
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Attendance)
    if employee_id:
        query = query.filter(Attendance.employee_id == employee_id)
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)
    if status:
        query = query.filter(Attendance.status == status)
    records = query.order_by(Attendance.date.desc()).offset(skip).limit(limit).all()
    return [AttendanceResponse.model_validate(r) for r in records]


@router.get("/summary/{employee_id}", response_model=AttendanceSummary)
def attendance_summary(
    employee_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    records = (
        db.query(Attendance)
        .filter(
            Attendance.employee_id == employee_id,
            extract("month", Attendance.date) == target_month,
            extract("year", Attendance.date) == target_year,
        )
        .all()
    )

    present = sum(1 for r in records if r.status == "present")
    absent = sum(1 for r in records if r.status == "absent")
    half_days = sum(1 for r in records if r.status == "half_day")
    wfh = sum(1 for r in records if r.status == "work_from_home")
    leave_days = sum(1 for r in records if r.status == "on_leave")
    hours = [r.work_hours for r in records if r.work_hours and r.work_hours > 0]
    avg_hours = round(sum(hours) / len(hours), 2) if hours else 0.0

    return AttendanceSummary(
        employee_id=employee_id,
        employee_name=f"{emp.first_name} {emp.last_name}",
        month=target_month,
        year=target_year,
        total_days=len(records),
        present_days=present,
        absent_days=absent,
        half_days=half_days,
        wfh_days=wfh,
        leave_days=leave_days,
        avg_work_hours=avg_hours,
    )


@router.post("/predict-capacity")
def predict_team_capacity(
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    att_query = (
        db.query(Attendance, Employee)
        .join(Employee, Attendance.employee_id == Employee.id)
        .filter(Attendance.date >= today.replace(day=1))
    )
    if department:
        att_query = att_query.filter(Employee.department.ilike(f"%{department}%"))
    attendance_results = att_query.all()

    att_lines = []
    for att, emp in attendance_results:
        att_lines.append(
            f"Employee: {emp.first_name} {emp.last_name} | Dept: {emp.department} | "
            f"Date: {att.date} | Status: {att.status} | Hours: {att.work_hours}"
        )

    leave_query = (
        db.query(LeaveRequest, Employee)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(LeaveRequest.status == "approved", LeaveRequest.end_date >= today)
    )
    if department:
        leave_query = leave_query.filter(Employee.department.ilike(f"%{department}%"))
    leave_results = leave_query.all()

    leave_lines = []
    for leave, emp in leave_results:
        leave_lines.append(
            f"Employee: {emp.first_name} {emp.last_name} | Dept: {emp.department} | "
            f"From: {leave.start_date} | To: {leave.end_date} | Type: {leave.leave_type}"
        )

    ai = GeminiService()
    prediction = ai.predict_team_capacity(
        "\n".join(att_lines) or "No recent attendance data",
        "\n".join(leave_lines) or "No upcoming leaves",
    )
    return {"prediction": prediction}
