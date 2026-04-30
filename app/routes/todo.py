from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app import models, schemas, auth
from app.dependencies import get_db

router = APIRouter(tags=["Todos"])


def normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -------- CREATE -------- #
@router.post("/todos/", response_model=schemas.TodoOut)
def create_todo(
    todo: schemas.TodoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo_data = todo.model_dump()
    if todo_data.get("reminder_time") is not None:
        todo_data["reminder_time"] = normalize_datetime(todo_data["reminder_time"])
    
    new_todo = models.Todo(**todo_data, owner_id=current_user.id)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

# -------- LIST -------- #
@router.get("/todos/", response_model=List[schemas.TodoOut])
def get_todos(
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query("id"),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    query = db.query(models.Todo).filter(models.Todo.owner_id == current_user.id)

    if status:
        query = query.filter(models.Todo.status == status)

    if sort in ["id", "title", "status"]:
        query = query.order_by(getattr(models.Todo, sort))

    return query.offset(offset).limit(limit).all()

# -------- GET ONE -------- #
@router.get("/todos/{todo_id}", response_model=schemas.TodoOut)
def get_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo

# -------- UPDATE -------- #
@router.put("/todos/{todo_id}", response_model=schemas.TodoOut)
def update_todo(
    todo_id: int,
    updated_data: schemas.TodoUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    update_dict = updated_data.model_dump(exclude_unset=True)
    
    if "reminder_time" in update_dict:
        update_dict["reminder_time"] = normalize_datetime(update_dict["reminder_time"])
    
    for key, value in update_dict.items():
        setattr(todo, key, value)

    db.commit()
    db.refresh(todo)
    return todo

# -------- DELETE -------- #
@router.delete("/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    db.delete(todo)
    db.commit()
    return {"detail": "Todo deleted"}


# -------- GET UPCOMING REMINDERS -------- #
@router.get("/todos/upcoming/", response_model=List[schemas.TodoOut])
def get_upcoming_todos(
    from_time: Optional[datetime] = Query(None, description="Start of time range (default: now, UTC)"),
    to_time: Optional[datetime] = Query(None, description="End of time range (UTC)"),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    normalized_from = normalize_datetime(from_time)
    normalized_to = normalize_datetime(to_time)

    if normalized_from is None:
        normalized_from = get_utc_now()

    if normalized_to is not None and normalized_to < normalized_from:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time range: to_time ({normalized_to.isoformat()}Z) cannot be earlier than from_time ({normalized_from.isoformat()}Z)"
        )

    query = db.query(models.Todo).filter(
        models.Todo.owner_id == current_user.id,
        models.Todo.reminder_time.isnot(None),
        models.Todo.status != "done"
    )

    query = query.filter(models.Todo.reminder_time >= normalized_from)

    if normalized_to is not None:
        query = query.filter(models.Todo.reminder_time <= normalized_to)

    query = query.order_by(models.Todo.reminder_time)

    return query.offset(offset).limit(limit).all()