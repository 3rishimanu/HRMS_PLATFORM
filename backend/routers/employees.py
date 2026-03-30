from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime
import csv
import io
import json

from database import get_db
from models.models import Employee, Document, User
from services.auth import get_current_user
from services.s3_service import upload_file
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/employees", tags=["Employees"])


# ---------- Schemas ----------

class EmployeeCreate(BaseModel):
    employee_code: Optional[str] = None
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    employment_type: Optional[str] = "full-time"
    date_of_joining: Optional[date] = None
    manager_id: Optional[int] = None
    salary: Optional[float] = 0
    skills: Optional[str] = None
    bio: Optional[str] = None


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    employment_type: Optional[str] = None
    date_of_joining: Optional[date] = None
    date_of_leaving: Optional[date] = None
    manager_id: Optional[int] = None
    salary: Optional[float] = None
    skills: Optional[str] = None
    bio: Optional[str] = None
    profile_picture: Optional[str] = None
    status: Optional[str] = None


class EmployeeResponse(BaseModel):
    id: int
    employee_code: Optional[str] = None
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    employment_type: Optional[str] = None
    date_of_joining: Optional[date] = None
    date_of_leaving: Optional[date] = None
    status: Optional[str] = None
    manager_id: Optional[int] = None
    salary: Optional[float] = None
    skills: Optional[str] = None
    bio: Optional[str] = None
    profile_picture: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: int
    employee_id: Optional[int] = None
    document_name: str
    document_type: Optional[str] = None
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrgChartNode(BaseModel):
    id: int
    name: str
    designation: Optional[str] = None
    department: Optional[str] = None
    profile_picture: Optional[str] = None
    children: List["OrgChartNode"] = []


OrgChartNode.model_rebuild()


# ---------- Routes ----------

@router.get("/org-chart", response_model=List[OrgChartNode])
def get_org_chart(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    employees = db.query(Employee).filter(Employee.status == "active").all()
    emp_map = {e.id: e for e in employees}

    def build_node(emp: Employee) -> OrgChartNode:
        children = [build_node(emp_map[c.id]) for c in employees if c.manager_id == emp.id]
        return OrgChartNode(
            id=emp.id,
            name=f"{emp.first_name} {emp.last_name}",
            designation=emp.designation,
            department=emp.department,
            profile_picture=emp.profile_picture,
            children=children,
        )

    roots = [e for e in employees if e.manager_id is None or e.manager_id not in emp_map]
    return [build_node(r) for r in roots]


@router.get("/export/csv")
def export_employees_csv(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    employees = db.query(Employee).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Employee Code", "First Name", "Last Name", "Email", "Phone",
        "Department", "Designation", "Employment Type", "Date of Joining",
        "Status", "Salary", "Skills",
    ])
    for e in employees:
        writer.writerow([
            e.id, e.employee_code, e.first_name, e.last_name, e.email, e.phone,
            e.department, e.designation, e.employment_type, e.date_of_joining,
            e.status, e.salary, e.skills,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees.csv"},
    )


@router.get("", response_model=List[EmployeeResponse])
def list_employees(
    search: Optional[str] = None,
    department: Optional[str] = None,
    skill: Optional[str] = None,
    designation: Optional[str] = None,
    status: Optional[str] = "active",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Employee)
    if status:
        query = query.filter(Employee.status == status)
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))
    if designation:
        query = query.filter(Employee.designation.ilike(f"%{designation}%"))
    if skill:
        query = query.filter(Employee.skills.ilike(f"%{skill}%"))
    if search:
        query = query.filter(
            (Employee.first_name.ilike(f"%{search}%"))
            | (Employee.last_name.ilike(f"%{search}%"))
            | (Employee.email.ilike(f"%{search}%"))
            | (Employee.employee_code.ilike(f"%{search}%"))
        )
    employees = query.offset(skip).limit(limit).all()
    return [EmployeeResponse.model_validate(e) for e in employees]


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Employee).filter(Employee.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Employee with this email already exists")
    emp = Employee(**payload.model_dump(exclude_none=True))
    if not emp.employee_code:
        count = db.query(Employee).count()
        emp.employee_code = f"EMP{count + 1:05d}"
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return EmployeeResponse.model_validate(emp)


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(employee_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return EmployeeResponse.model_validate(emp)


@router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(emp, key, value)
    db.commit()
    db.refresh(emp)
    return EmployeeResponse.model_validate(emp)


@router.delete("/{employee_id}", response_model=EmployeeResponse)
def deactivate_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.status = "inactive"
    emp.date_of_leaving = date.today()
    db.commit()
    db.refresh(emp)
    return EmployeeResponse.model_validate(emp)


@router.post("/{employee_id}/documents", response_model=DocumentResponse)
async def upload_employee_document(
    employee_id: int,
    file: UploadFile = File(...),
    document_type: str = Query("other"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    file_url = await upload_file(file, folder=f"employees/{employee_id}")
    doc = Document(
        employee_id=employee_id,
        document_name=file.filename or "untitled",
        document_type=document_type,
        file_url=file_url,
        file_size=file.size,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.get("/{employee_id}/documents", response_model=List[DocumentResponse])
def list_employee_documents(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    docs = db.query(Document).filter(Document.employee_id == employee_id).all()
    return [DocumentResponse.model_validate(d) for d in docs]


@router.post("/{employee_id}/generate-bio")
def generate_bio(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    ai = GeminiService()
    bio = ai.generate_employee_bio(
        name=f"{emp.first_name} {emp.last_name}",
        designation=emp.designation or "N/A",
        department=emp.department or "N/A",
        skills=emp.skills or "N/A",
    )
    emp.bio = bio
    db.commit()
    db.refresh(emp)
    return {"employee_id": emp.id, "bio": bio}


@router.post("/detect-duplicates")
def detect_duplicates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employees = db.query(Employee).all()
    data_lines = []
    for e in employees:
        data_lines.append(
            f"ID:{e.id} | Name:{e.first_name} {e.last_name} | Email:{e.email} | "
            f"Phone:{e.phone} | Dept:{e.department} | Designation:{e.designation} | "
            f"Skills:{e.skills} | DOB:{e.date_of_birth}"
        )
    ai = GeminiService()
    result = ai.detect_duplicate_profiles("\n".join(data_lines))
    return {"analysis": result}
