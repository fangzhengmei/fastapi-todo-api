from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app import models, schemas, auth
from app.dependencies import get_db

router = APIRouter(tags=["Todos"])


# -------- CREATE -------- #
@router.post("/todos/", response_model=schemas.TodoOut)
def create_todo(
    todo: schemas.TodoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    new_todo = models.Todo(**todo.dict(), owner_id=current_user.id)
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
    query = db.query(models.Todo).filter(
        models.Todo.owner_id == current_user.id,
        models.Todo.is_deleted == False
    )

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
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=False
    ).first()
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
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=False
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    for key, value in updated_data.dict(exclude_unset=True).items():
        setattr(todo, key, value)

    db.commit()
    db.refresh(todo)
    return todo

# -------- DELETE (Soft Delete) -------- #
@router.delete("/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=False
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    todo.is_deleted = True
    todo.deleted_at = datetime.utcnow()
    db.commit()
    return {"detail": "Todo moved to trash"}

# -------- TRASH: List Deleted Todos -------- #
@router.get("/todos/trash/", response_model=List[schemas.TodoOut])
def get_trash(
    sort: Optional[str] = Query("deleted_at"),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    query = db.query(models.Todo).filter(
        models.Todo.owner_id == current_user.id,
        models.Todo.is_deleted == True
    )

    if sort in ["id", "title", "status", "deleted_at"]:
        query = query.order_by(getattr(models.Todo, sort).desc())

    return query.offset(offset).limit(limit).all()

# -------- TRASH: Get Single Deleted Todo -------- #
@router.get("/todos/trash/{todo_id}", response_model=schemas.TodoOut)
def get_trash_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=True
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found in trash")
    return todo

# -------- TRASH: Restore Todo -------- #
@router.post("/todos/{todo_id}/restore", response_model=schemas.TodoOut)
def restore_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=True
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found in trash")

    todo.is_deleted = False
    todo.deleted_at = None
    db.commit()
    db.refresh(todo)
    return todo

# -------- TRASH: Permanent Delete -------- #
@router.delete("/todos/{todo_id}/permanent")
def permanent_delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(
        id=todo_id, 
        owner_id=current_user.id,
        is_deleted=True
    ).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found in trash")

    db.delete(todo)
    db.commit()
    return {"detail": "Todo permanently deleted"}

# -------- TRASH: Empty All -------- #
@router.delete("/todos/trash/empty")
def empty_trash(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    deleted_count = db.query(models.Todo).filter(
        models.Todo.owner_id == current_user.id,
        models.Todo.is_deleted == True
    ).delete(synchronize_session=False)
    
    db.commit()
    return {"detail": f"Emptied {deleted_count} items from trash"}

# -------- TRASH: Auto Cleanup Logic -------- #
def auto_cleanup_trash(db: Session, user: models.User):
    """
    Automatically permanently delete todos that have been in trash
    for longer than the user's configured auto-clean days.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=user.trash_auto_clean_days)
    
    deleted_count = db.query(models.Todo).filter(
        models.Todo.owner_id == user.id,
        models.Todo.is_deleted == True,
        models.Todo.deleted_at <= cutoff_date
    ).delete(synchronize_session=False)
    
    db.commit()
    return deleted_count

# -------- TRASH: Manual Trigger Auto Cleanup -------- #
@router.post("/todos/trash/cleanup", response_model=schemas.TrashCleanupResult)
def manual_cleanup_trash(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Manually trigger the auto-cleanup process for the current user's trash.
    This will permanently delete all todos that have been in trash for longer
    than the user's configured auto-clean days.
    """
    cleaned_count = auto_cleanup_trash(db, current_user)
    
    return {
        "cleaned_count": cleaned_count,
        "message": f"Auto-cleanup completed. Permanently deleted {cleaned_count} items from trash."
    }