from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime
import json

from database import get_db
from models.models import JobPosting, Candidate, User
from services.auth import get_current_user
from services.s3_service import upload_file
from ai.gemini_service import GeminiService

router = APIRouter(tags=["Recruitment"])


# ---------- Schemas ----------

class JobCreate(BaseModel):
    title: str
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = "full-time"
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    status: Optional[str] = "open"
    closing_date: Optional[date] = None


class JobUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    status: Optional[str] = None
    closing_date: Optional[date] = None


class JobResponse(BaseModel):
    id: int
    title: str
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    status: Optional[str] = None
    posted_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closing_date: Optional[date] = None

    class Config:
        from_attributes = True


class CandidateResponse(BaseModel):
    id: int
    job_id: int
    name: str
    email: str
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    cover_letter: Optional[str] = None
    stage: Optional[str] = None
    score: Optional[float] = None
    ai_summary: Optional[str] = None
    interview_questions: Optional[str] = None
    applied_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StageUpdate(BaseModel):
    stage: str


class JobWithCandidates(JobResponse):
    candidates: List[CandidateResponse] = []


# ---------- Routes ----------

@router.get("/api/jobs", response_model=List[JobResponse])
def list_jobs(
    status: Optional[str] = None,
    department: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(JobPosting)
    if status:
        query = query.filter(JobPosting.status == status)
    if department:
        query = query.filter(JobPosting.department.ilike(f"%{department}%"))
    jobs = query.order_by(JobPosting.created_at.desc()).offset(skip).limit(limit).all()
    return [JobResponse.model_validate(j) for j in jobs]


@router.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = JobPosting(**payload.model_dump(exclude_none=True), posted_by=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.get("/api/jobs/{job_id}", response_model=JobWithCandidates)
def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    candidates = [CandidateResponse.model_validate(c) for c in job.candidates]
    resp = JobWithCandidates.model_validate(job)
    resp.candidates = candidates
    return resp


@router.put("/api/jobs/{job_id}", response_model=JobResponse)
def update_job(
    job_id: int,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.get("/api/jobs/{job_id}/candidates", response_model=List[CandidateResponse])
def list_candidates(
    job_id: int,
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    query = db.query(Candidate).filter(Candidate.job_id == job_id)
    if stage:
        query = query.filter(Candidate.stage == stage)
    candidates = query.order_by(Candidate.applied_at.desc()).all()
    return [CandidateResponse.model_validate(c) for c in candidates]


@router.post("/api/jobs/{job_id}/candidates", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def add_candidate(
    job_id: int,
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    cover_letter: Optional[str] = Form(None),
    resume: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    resume_url = None
    resume_text = None
    if resume:
        resume_url = await upload_file(resume, folder=f"resumes/{job_id}")
        await resume.seek(0)
        try:
            content = await resume.read()
            resume_text = content.decode("utf-8", errors="ignore")
        except Exception:
            resume_text = None

    candidate = Candidate(
        job_id=job_id,
        name=name,
        email=email,
        phone=phone,
        cover_letter=cover_letter,
        resume_url=resume_url,
        resume_text=resume_text,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return CandidateResponse.model_validate(candidate)


@router.put("/api/candidates/{candidate_id}/stage", response_model=CandidateResponse)
def update_candidate_stage(
    candidate_id: int,
    payload: StageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    candidate.stage = payload.stage
    db.commit()
    db.refresh(candidate)
    return CandidateResponse.model_validate(candidate)


@router.post("/api/candidates/{candidate_id}/score")
def score_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = db.query(JobPosting).filter(JobPosting.id == candidate.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    if not candidate.resume_text:
        raise HTTPException(status_code=400, detail="No resume text available for scoring")

    ai = GeminiService()
    jd = f"Title: {job.title}\nDescription: {job.description}\nRequirements: {job.requirements}"
    result = ai.score_resume(candidate.resume_text, jd)

    try:
        clean = result.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
        score_data = json.loads(clean)
        candidate.score = score_data.get("total_score", 0)
    except (json.JSONDecodeError, ValueError):
        candidate.score = None

    candidate.ai_summary = result
    db.commit()
    db.refresh(candidate)
    return {"candidate_id": candidate.id, "score": candidate.score, "analysis": result}


@router.post("/api/candidates/{candidate_id}/questions")
def generate_interview_questions(
    candidate_id: int,
    num_questions: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = db.query(JobPosting).filter(JobPosting.id == candidate.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    ai = GeminiService()
    jd = f"Title: {job.title}\nDescription: {job.description}\nRequirements: {job.requirements}"
    result = ai.generate_interview_questions(jd, candidate.resume_text or "", num_questions)
    candidate.interview_questions = result
    db.commit()
    return {"candidate_id": candidate.id, "questions": result}


@router.get("/api/jobs/{job_id}/compare")
def compare_candidates(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    shortlisted = (
        db.query(Candidate)
        .filter(Candidate.job_id == job_id, Candidate.stage == "shortlisted")
        .all()
    )
    if len(shortlisted) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 shortlisted candidates to compare")

    candidates_data = "\n\n".join(
        f"Name: {c.name}\nScore: {c.score}\nResume: {c.resume_text or 'N/A'}\nSummary: {c.ai_summary or 'N/A'}"
        for c in shortlisted
    )
    jd = f"Title: {job.title}\nDescription: {job.description}\nRequirements: {job.requirements}"
    ai = GeminiService()
    result = ai.compare_candidates(candidates_data, jd)
    return {"job_id": job_id, "candidates_count": len(shortlisted), "comparison": result}
