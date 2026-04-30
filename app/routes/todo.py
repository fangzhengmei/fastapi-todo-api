from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app import models, schemas, auth
from app.dependencies import get_db
from app.time_utils import (
    normalize_to_utc_naive,
    get_utc_now_naive,
    validate_time_range
)

router = APIRouter(tags=["Todos"])


# -------- CREATE -------- #
@router.post("/todos/", response_model=schemas.TodoOut)
def create_todo(
    todo: schemas.TodoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo_data = todo.model_dump()
    if todo_data.get("reminder_time") is not None:
        todo_data["reminder_time"] = normalize_to_utc_naive(todo_data["reminder_time"])
    
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
        update_dict["reminder_time"] = normalize_to_utc_naive(update_dict["reminder_time"])
    
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
    from_time: Optional[datetime] = Query(None, description="Start of time range (inclusive, default: now UTC). Timezone-aware inputs are converted to UTC; timezone-naive inputs are treated as UTC."),
    to_time: Optional[datetime] = Query(None, description="End of time range (inclusive). Timezone-aware inputs are converted to UTC; timezone-naive inputs are treated as UTC."),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        normalized_from, normalized_to = validate_time_range(
            from_time=from_time,
            to_time=to_time
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
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