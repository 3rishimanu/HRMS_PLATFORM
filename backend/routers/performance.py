from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
import io

from database import get_db
from models.models import ReviewCycle, PerformanceReview, Employee, User
from services.auth import get_current_user
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/reviews", tags=["Performance Reviews"])


# ---------- Schemas ----------

class CycleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    status: Optional[str] = "active"


class CycleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReviewCreate(BaseModel):
    cycle_id: int
    employee_id: int
    reviewer_id: Optional[int] = None
    goals: Optional[str] = None
    achievements: Optional[str] = None


class SelfAssessment(BaseModel):
    self_rating: float
    self_comments: Optional[str] = None
    achievements: Optional[str] = None
    goals: Optional[str] = None


class ManagerReview(BaseModel):
    manager_rating: float
    manager_comments: Optional[str] = None
    areas_of_improvement: Optional[str] = None


class ReviewResponse(BaseModel):
    id: int
    cycle_id: int
    employee_id: int
    reviewer_id: Optional[int] = None
    self_rating: Optional[float] = None
    self_comments: Optional[str] = None
    manager_rating: Optional[float] = None
    manager_comments: Optional[str] = None
    goals: Optional[str] = None
    achievements: Optional[str] = None
    areas_of_improvement: Optional[str] = None
    overall_rating: Optional[float] = None
    ai_summary: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CycleWithReviews(CycleResponse):
    reviews: List[ReviewResponse] = []


# ---------- Routes ----------

@router.get("/cycles", response_model=List[CycleResponse])
def list_cycles(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ReviewCycle)
    if status:
        query = query.filter(ReviewCycle.status == status)
    cycles = query.order_by(ReviewCycle.created_at.desc()).all()
    return [CycleResponse.model_validate(c) for c in cycles]


@router.post("/cycles", response_model=CycleResponse, status_code=status.HTTP_201_CREATED)
def create_cycle(
    payload: CycleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cycle = ReviewCycle(**payload.model_dump(exclude_none=True))
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return CycleResponse.model_validate(cycle)


@router.get("/cycles/{cycle_id}", response_model=CycleWithReviews)
def get_cycle(
    cycle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cycle = db.query(ReviewCycle).filter(ReviewCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Review cycle not found")
    reviews = [ReviewResponse.model_validate(r) for r in cycle.reviews]
    resp = CycleWithReviews.model_validate(cycle)
    resp.reviews = reviews
    return resp


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cycle = db.query(ReviewCycle).filter(ReviewCycle.id == payload.cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Review cycle not found")
    emp = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    existing = (
        db.query(PerformanceReview)
        .filter(
            PerformanceReview.cycle_id == payload.cycle_id,
            PerformanceReview.employee_id == payload.employee_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Review already exists for this employee in this cycle")

    review = PerformanceReview(**payload.model_dump(exclude_none=True))
    db.add(review)
    db.commit()
    db.refresh(review)
    return ReviewResponse.model_validate(review)


@router.put("/{review_id}/self-assessment", response_model=ReviewResponse)
def submit_self_assessment(
    review_id: int,
    payload: SelfAssessment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.self_rating = payload.self_rating
    review.self_comments = payload.self_comments
    if payload.achievements:
        review.achievements = payload.achievements
    if payload.goals:
        review.goals = payload.goals
    review.status = "self_review"
    db.commit()
    db.refresh(review)
    return ReviewResponse.model_validate(review)


@router.put("/{review_id}/manager-review", response_model=ReviewResponse)
def submit_manager_review(
    review_id: int,
    payload: ManagerReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.manager_rating = payload.manager_rating
    review.manager_comments = payload.manager_comments
    if payload.areas_of_improvement:
        review.areas_of_improvement = payload.areas_of_improvement

    if review.self_rating is not None:
        review.overall_rating = round((review.self_rating + payload.manager_rating) / 2, 2)
    else:
        review.overall_rating = payload.manager_rating

    review.status = "completed"
    review.reviewer_id = current_user.employee_id
    db.commit()
    db.refresh(review)
    return ReviewResponse.model_validate(review)


@router.post("/{review_id}/generate-summary")
def generate_review_summary(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    emp = db.query(Employee).filter(Employee.id == review.employee_id).first()

    review_data = (
        f"Employee: {emp.first_name} {emp.last_name}\n"
        f"Department: {emp.department}\nDesignation: {emp.designation}\n"
        f"Self Rating: {review.self_rating}\nSelf Comments: {review.self_comments}\n"
        f"Manager Rating: {review.manager_rating}\nManager Comments: {review.manager_comments}\n"
        f"Goals: {review.goals}\nAchievements: {review.achievements}\n"
        f"Areas of Improvement: {review.areas_of_improvement}\n"
        f"Overall Rating: {review.overall_rating}"
    )
    ai = GeminiService()
    summary = ai.generate_review_summary(review_data)
    review.ai_summary = summary
    db.commit()
    return {"review_id": review.id, "summary": summary}


@router.get("/{review_id}/export-pdf")
def export_review_pdf(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    review = db.query(PerformanceReview).filter(PerformanceReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    emp = db.query(Employee).filter(Employee.id == review.employee_id).first()
    cycle = db.query(ReviewCycle).filter(ReviewCycle.id == review.cycle_id).first()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, spaceAfter=20)
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=14, spaceAfter=10, textColor=colors.HexColor("#1a56db"))
    body_style = styles["BodyText"]

    elements = []
    elements.append(Paragraph("Performance Review Report", title_style))
    elements.append(Paragraph(f"HireFlow AI - {cycle.name if cycle else 'N/A'}", styles["Heading3"]))
    elements.append(Spacer(1, 20))

    info_data = [
        ["Employee", f"{emp.first_name} {emp.last_name}" if emp else "N/A"],
        ["Department", emp.department or "N/A" if emp else "N/A"],
        ["Designation", emp.designation or "N/A" if emp else "N/A"],
        ["Review Period", f"{cycle.start_date} to {cycle.end_date}" if cycle else "N/A"],
        ["Status", review.status or "N/A"],
    ]
    info_table = Table(info_data, colWidths=[2 * inch, 4 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 20))

    ratings_data = [
        ["Rating Type", "Score"],
        ["Self Rating", str(review.self_rating or "N/A")],
        ["Manager Rating", str(review.manager_rating or "N/A")],
        ["Overall Rating", str(review.overall_rating or "N/A")],
    ]
    ratings_table = Table(ratings_data, colWidths=[3 * inch, 3 * inch])
    ratings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a56db")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]))
    elements.append(Paragraph("Ratings", heading_style))
    elements.append(ratings_table)
    elements.append(Spacer(1, 15))

    sections = [
        ("Self Comments", review.self_comments),
        ("Manager Comments", review.manager_comments),
        ("Goals", review.goals),
        ("Achievements", review.achievements),
        ("Areas of Improvement", review.areas_of_improvement),
        ("AI Summary", review.ai_summary),
    ]
    for section_title, content in sections:
        if content:
            elements.append(Paragraph(section_title, heading_style))
            elements.append(Paragraph(content, body_style))
            elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    filename = f"review_{emp.first_name}_{emp.last_name}_{review.id}.pdf" if emp else f"review_{review.id}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
