from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import Optional
from datetime import date, datetime, timedelta

from database import get_db
from models.models import (
    Employee, JobPosting, LeaveRequest, LeaveBalance,
    Attendance, PerformanceReview, User,
)
from services.auth import get_current_user
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/headcount")
def headcount_by_department(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = (
        db.query(Employee.department, func.count(Employee.id))
        .filter(Employee.status == "active")
        .group_by(Employee.department)
        .all()
    )
    total = sum(count for _, count in results)
    departments = [
        {"department": dept or "Unassigned", "count": count}
        for dept, count in results
    ]
    return {"total_headcount": total, "departments": departments}


@router.get("/attrition")
def attrition_rate(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_year = year or date.today().year

    left_count = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.date_of_leaving.isnot(None),
            extract("year", Employee.date_of_leaving) == target_year,
        )
        .scalar()
    )

    avg_headcount_start = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.date_of_joining <= date(target_year, 1, 1),
            (Employee.date_of_leaving.is_(None)) | (Employee.date_of_leaving >= date(target_year, 1, 1)),
        )
        .scalar()
    )
    avg_headcount_end = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.date_of_joining <= date(target_year, 12, 31),
            (Employee.date_of_leaving.is_(None)) | (Employee.date_of_leaving >= date(target_year, 12, 31)),
        )
        .scalar()
    )
    avg_headcount = (avg_headcount_start + avg_headcount_end) / 2 if (avg_headcount_start + avg_headcount_end) > 0 else 1

    attrition_pct = round((left_count / avg_headcount) * 100, 2) if avg_headcount > 0 else 0

    by_dept = (
        db.query(Employee.department, func.count(Employee.id))
        .filter(
            Employee.date_of_leaving.isnot(None),
            extract("year", Employee.date_of_leaving) == target_year,
        )
        .group_by(Employee.department)
        .all()
    )

    return {
        "year": target_year,
        "total_attrition": left_count,
        "attrition_rate": attrition_pct,
        "by_department": [
            {"department": dept or "Unassigned", "count": count}
            for dept, count in by_dept
        ],
    }


@router.get("/tenure")
def average_tenure(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employees = (
        db.query(Employee)
        .filter(Employee.status == "active", Employee.date_of_joining.isnot(None))
        .all()
    )
    today = date.today()
    dept_tenure = {}
    for emp in employees:
        dept = emp.department or "Unassigned"
        years = (today - emp.date_of_joining).days / 365.25
        dept_tenure.setdefault(dept, []).append(years)

    result = []
    for dept, tenures in dept_tenure.items():
        result.append({
            "department": dept,
            "avg_tenure_years": round(sum(tenures) / len(tenures), 2),
            "employee_count": len(tenures),
        })

    overall = sum(t for ts in dept_tenure.values() for t in ts)
    total = sum(len(ts) for ts in dept_tenure.values())
    return {
        "overall_avg_tenure_years": round(overall / total, 2) if total > 0 else 0,
        "departments": result,
    }


@router.get("/positions")
def open_vs_filled(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    open_jobs = db.query(func.count(JobPosting.id)).filter(JobPosting.status == "open").scalar()
    closed_jobs = db.query(func.count(JobPosting.id)).filter(JobPosting.status == "closed").scalar()
    on_hold = db.query(func.count(JobPosting.id)).filter(JobPosting.status == "on_hold").scalar()
    total = db.query(func.count(JobPosting.id)).scalar()

    by_dept = (
        db.query(JobPosting.department, JobPosting.status, func.count(JobPosting.id))
        .group_by(JobPosting.department, JobPosting.status)
        .all()
    )
    dept_data = {}
    for dept, st, cnt in by_dept:
        d = dept or "Unassigned"
        dept_data.setdefault(d, {})
        dept_data[d][st] = cnt

    return {
        "total": total,
        "open": open_jobs,
        "closed": closed_jobs,
        "on_hold": on_hold,
        "by_department": [
            {"department": dept, **statuses}
            for dept, statuses in dept_data.items()
        ],
    }


@router.get("/leave-utilization")
def leave_utilization(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_year = year or date.today().year
    balances = db.query(LeaveBalance).filter(LeaveBalance.year == target_year).all()

    by_type = {}
    for b in balances:
        by_type.setdefault(b.leave_type, {"total": 0, "used": 0, "remaining": 0})
        by_type[b.leave_type]["total"] += b.total_days
        by_type[b.leave_type]["used"] += b.used_days
        by_type[b.leave_type]["remaining"] += b.remaining_days

    utilization = []
    for lt, data in by_type.items():
        rate = round((data["used"] / data["total"]) * 100, 2) if data["total"] > 0 else 0
        utilization.append({
            "leave_type": lt,
            "total_allocated": data["total"],
            "total_used": data["used"],
            "total_remaining": data["remaining"],
            "utilization_rate": rate,
        })

    return {"year": target_year, "utilization": utilization}


@router.post("/generate-summary")
def generate_hr_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active_count = db.query(func.count(Employee.id)).filter(Employee.status == "active").scalar()
    inactive_count = db.query(func.count(Employee.id)).filter(Employee.status == "inactive").scalar()
    open_jobs = db.query(func.count(JobPosting.id)).filter(JobPosting.status == "open").scalar()
    pending_leaves = db.query(func.count(LeaveRequest.id)).filter(LeaveRequest.status == "pending").scalar()
    approved_leaves = db.query(func.count(LeaveRequest.id)).filter(LeaveRequest.status == "approved").scalar()

    dept_counts = (
        db.query(Employee.department, func.count(Employee.id))
        .filter(Employee.status == "active")
        .group_by(Employee.department)
        .all()
    )

    analytics_text = (
        f"Active Employees: {active_count}\n"
        f"Inactive Employees: {inactive_count}\n"
        f"Open Job Postings: {open_jobs}\n"
        f"Pending Leave Requests: {pending_leaves}\n"
        f"Approved Leaves (current): {approved_leaves}\n"
        f"Department-wise headcount:\n"
        + "\n".join(f"  {dept or 'Unassigned'}: {cnt}" for dept, cnt in dept_counts)
    )

    ai = GeminiService()
    summary = ai.generate_hr_summary(analytics_text)
    return {"summary": summary}


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()

    active_employees = db.query(func.count(Employee.id)).filter(Employee.status == "active").scalar()
    total_employees = db.query(func.count(Employee.id)).scalar()
    open_positions = db.query(func.count(JobPosting.id)).filter(JobPosting.status == "open").scalar()
    pending_leaves = db.query(func.count(LeaveRequest.id)).filter(LeaveRequest.status == "pending").scalar()

    new_hires_month = (
        db.query(func.count(Employee.id))
        .filter(
            Employee.date_of_joining.isnot(None),
            extract("month", Employee.date_of_joining) == today.month,
            extract("year", Employee.date_of_joining) == today.year,
        )
        .scalar()
    )

    dept_counts = (
        db.query(Employee.department, func.count(Employee.id))
        .filter(Employee.status == "active")
        .group_by(Employee.department)
        .all()
    )

    today_present = (
        db.query(func.count(Attendance.id))
        .filter(Attendance.date == today, Attendance.status == "present")
        .scalar()
    )

    return {
        "active_employees": active_employees,
        "total_employees": total_employees,
        "open_positions": open_positions,
        "pending_leave_requests": pending_leaves,
        "new_hires_this_month": new_hires_month,
        "today_attendance": today_present,
        "departments": [
            {"department": dept or "Unassigned", "count": cnt}
            for dept, cnt in dept_counts
        ],
    }
