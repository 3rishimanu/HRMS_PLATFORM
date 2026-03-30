from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json

from database import get_db
from models.models import (
    OnboardingChecklist, OnboardingProgress, ChatMessage, Document, Employee, User,
)
from services.auth import get_current_user
from services.s3_service import upload_file
from ai.gemini_service import GeminiService

router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])


# ---------- Schemas ----------

class ChecklistCreate(BaseModel):
    title: str
    description: Optional[str] = None
    department: Optional[str] = None
    items: str  # JSON string of checklist items


class ChecklistResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    department: Optional[str] = None
    items: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProgressResponse(BaseModel):
    id: int
    employee_id: int
    checklist_id: int
    completed_items: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    checklist: Optional[ChecklistResponse] = None

    class Config:
        from_attributes = True


class CompleteItemRequest(BaseModel):
    checklist_id: int
    item_key: str


class ChatRequest(BaseModel):
    employee_id: int
    message: str


class ChatResponse(BaseModel):
    id: int
    employee_id: int
    message: str
    response: Optional[str] = None
    message_type: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Routes ----------

@router.get("/checklists", response_model=List[ChecklistResponse])
def list_checklists(
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(OnboardingChecklist)
    if department:
        query = query.filter(OnboardingChecklist.department.ilike(f"%{department}%"))
    checklists = query.order_by(OnboardingChecklist.created_at.desc()).all()
    return [ChecklistResponse.model_validate(c) for c in checklists]


@router.post("/checklists", response_model=ChecklistResponse, status_code=status.HTTP_201_CREATED)
def create_checklist(
    payload: ChecklistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    checklist = OnboardingChecklist(
        title=payload.title,
        description=payload.description,
        department=payload.department,
        items=payload.items,
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return ChecklistResponse.model_validate(checklist)


@router.get("/progress/{employee_id}", response_model=List[ProgressResponse])
def get_onboarding_progress(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    progress_records = (
        db.query(OnboardingProgress)
        .filter(OnboardingProgress.employee_id == employee_id)
        .all()
    )

    if not progress_records:
        dept = emp.department
        checklists = db.query(OnboardingChecklist).filter(
            (OnboardingChecklist.department == dept) | (OnboardingChecklist.department.is_(None))
        ).all()
        for cl in checklists:
            prog = OnboardingProgress(
                employee_id=employee_id,
                checklist_id=cl.id,
                completed_items="[]",
            )
            db.add(prog)
        db.commit()
        progress_records = (
            db.query(OnboardingProgress)
            .filter(OnboardingProgress.employee_id == employee_id)
            .all()
        )

    results = []
    for p in progress_records:
        resp = ProgressResponse.model_validate(p)
        resp.checklist = ChecklistResponse.model_validate(p.checklist) if p.checklist else None
        results.append(resp)
    return results


@router.put("/progress/{employee_id}/complete-item", response_model=ProgressResponse)
def complete_checklist_item(
    employee_id: int,
    payload: CompleteItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    progress = (
        db.query(OnboardingProgress)
        .filter(
            OnboardingProgress.employee_id == employee_id,
            OnboardingProgress.checklist_id == payload.checklist_id,
        )
        .first()
    )
    if not progress:
        raise HTTPException(status_code=404, detail="Onboarding progress not found")

    try:
        completed = json.loads(progress.completed_items or "[]")
    except json.JSONDecodeError:
        completed = []

    if payload.item_key not in completed:
        completed.append(payload.item_key)
    progress.completed_items = json.dumps(completed)

    checklist = db.query(OnboardingChecklist).filter(OnboardingChecklist.id == payload.checklist_id).first()
    if checklist and checklist.items:
        try:
            all_items = json.loads(checklist.items)
            item_keys = [item.get("key", item.get("id", "")) for item in all_items] if isinstance(all_items, list) else list(all_items.keys())
            if set(item_keys).issubset(set(completed)):
                progress.status = "completed"
                progress.completed_at = datetime.utcnow()
        except json.JSONDecodeError:
            pass

    db.commit()
    db.refresh(progress)
    resp = ProgressResponse.model_validate(progress)
    resp.checklist = ChecklistResponse.model_validate(progress.checklist) if progress.checklist else None
    return resp


@router.post("/chat", response_model=ChatResponse)
def onboarding_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    policy_docs = db.query(Document).filter(Document.is_policy == True).all()
    policy_context = "\n\n".join(
        f"Document: {d.document_name}\n{d.content_text or ''}"
        for d in policy_docs
    )
    if not policy_context:
        policy_context = "No policy documents have been uploaded yet. Please provide general HR guidance."

    ai = GeminiService()
    response_text = ai.answer_policy_question(payload.message, policy_context)

    chat_msg = ChatMessage(
        employee_id=payload.employee_id,
        message=payload.message,
        response=response_text,
        message_type="question",
    )
    db.add(chat_msg)
    db.commit()
    db.refresh(chat_msg)
    return ChatResponse.model_validate(chat_msg)


@router.get("/chat/history/{employee_id}", response_model=List[ChatResponse])
def get_chat_history(
    employee_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.employee_id == employee_id)
        .order_by(ChatMessage.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [ChatResponse.model_validate(m) for m in messages]


@router.get("/chat/frequent-questions")
def frequent_questions(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = (
        db.query(ChatMessage.message, func.count(ChatMessage.id).label("count"))
        .group_by(ChatMessage.message)
        .order_by(func.count(ChatMessage.id).desc())
        .limit(limit)
        .all()
    )
    return [{"question": r[0], "count": r[1]} for r in results]


@router.post("/documents")
async def upload_policy_document(
    file: UploadFile = File(...),
    document_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_url = await upload_file(file, folder="policies")

    content_text = None
    await file.seek(0)
    try:
        raw = await file.read()
        if file.filename and file.filename.lower().endswith(".pdf"):
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            pages_text = []
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")
            content_text = "\n".join(pages_text)
        else:
            content_text = raw.decode("utf-8", errors="ignore")
    except Exception:
        content_text = None

    doc = Document(
        document_name=document_name or file.filename or "policy_doc",
        document_type="policy",
        file_url=file_url,
        file_size=file.size,
        is_policy=True,
        content_text=content_text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {
        "id": doc.id,
        "document_name": doc.document_name,
        "file_url": doc.file_url,
        "uploaded_at": doc.uploaded_at,
    }
