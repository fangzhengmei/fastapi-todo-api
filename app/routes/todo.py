from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from app import models, schemas, auth
from app.dependencies import get_db, get_access_context, is_user_share_valid, AccessContext

router = APIRouter(tags=["Todos"])


@dataclass
class AccessCheckResult:
    todo: Optional[models.Todo] = None
    has_read_access: bool = False
    has_write_access: bool = False
    todo_exists: bool = False


def check_todo_access(
    db: Session,
    todo_id: int,
    user: Optional[models.User],
    share_link: Optional[models.TodoShareLink],
) -> AccessCheckResult:
    result = AccessCheckResult()
    
    todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    
    if not todo:
        return result
    
    result.todo = todo
    result.todo_exists = True
    
    if user:
        if todo.owner_id == user.id:
            result.has_read_access = True
            result.has_write_access = True
            return result
        
        share = db.query(models.TodoShare).filter(
            models.TodoShare.todo_id == todo_id,
            models.TodoShare.shared_with_id == user.id
        ).first()
        
        if share and is_user_share_valid(share):
            result.has_read_access = True
            result.has_write_access = (share.permission == "read_write")
            return result
    
    if share_link:
        if share_link.todo_id == todo_id:
            result.has_read_access = True
            result.has_write_access = (share_link.permission == "read_write")
            return result
    
    return result


# -------- CREATE -------- #
@router.post("/todos/", response_model=schemas.TodoOut)
def create_todo(
    todo: schemas.TodoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    new_todo = models.Todo(**todo.model_dump(), owner_id=current_user.id)
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
    include_shared: bool = Query(False, description="Include todos shared with me (only for authenticated users)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if include_shared:
        valid_shares = db.query(models.TodoShare.todo_id).filter(
            models.TodoShare.shared_with_id == current_user.id,
            or_(
                models.TodoShare.expires_at.is_(None),
                models.TodoShare.expires_at > datetime.utcnow()
            )
        ).all()
        
        valid_todo_ids = [share.todo_id for share in valid_shares]
        
        if valid_todo_ids:
            query = db.query(models.Todo).filter(
                or_(
                    models.Todo.owner_id == current_user.id,
                    models.Todo.id.in_(valid_todo_ids)
                )
            )
        else:
            query = db.query(models.Todo).filter(models.Todo.owner_id == current_user.id)
    else:
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
    context: AccessContext = Depends(get_access_context)
):
    if not context.has_credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: provide Bearer token or X-Share-Token header"
        )
    
    result = check_todo_access(db, todo_id, context.user, context.share_link)
    
    if not result.has_read_access:
        raise HTTPException(status_code=404, detail="Todo not found or access denied")
    
    return result.todo

# -------- UPDATE -------- #
@router.put("/todos/{todo_id}", response_model=schemas.TodoOut)
def update_todo(
    todo_id: int,
    updated_data: schemas.TodoUpdate,
    db: Session = Depends(get_db),
    context: AccessContext = Depends(get_access_context)
):
    if not context.has_credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: provide Bearer token or X-Share-Token header"
        )
    
    result = check_todo_access(db, todo_id, context.user, context.share_link)
    
    if not result.has_read_access:
        raise HTTPException(status_code=404, detail="Todo not found or access denied")
    
    if not result.has_write_access:
        raise HTTPException(status_code=403, detail="Not authorized to update this todo")

    for key, value in updated_data.model_dump(exclude_unset=True).items():
        setattr(result.todo, key, value)

    db.commit()
    db.refresh(result.todo)
    return result.todo

# -------- DELETE -------- #
@router.delete("/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found or not authorized to delete")

    db.delete(todo)
    db.commit()
    return {"detail": "Todo deleted"}
