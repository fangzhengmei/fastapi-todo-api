from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime
import uuid

from app import models, schemas, auth
from app.dependencies import get_db
from app.config import settings

router = APIRouter(tags=["Shares"])

VALID_PERMISSIONS = ["read_only", "read_write"]


def validate_permission(permission: str):
    if permission not in VALID_PERMISSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permission. Must be one of: {', '.join(VALID_PERMISSIONS)}"
        )
    return permission


def build_share_url(request: Request, share_token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/share-links/{share_token}/access"


def is_share_valid(share: models.TodoShare) -> bool:
    if share.expires_at and share.expires_at < datetime.utcnow():
        return False
    return True


def is_share_link_valid(share_link: models.TodoShareLink) -> bool:
    if not share_link.is_active:
        return False
    if share_link.expires_at and share_link.expires_at < datetime.utcnow():
        return False
    return True


def get_todo_with_share(
    db: Session,
    todo_id: int,
    user: models.User
) -> Optional[models.Todo]:
    todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    
    if not todo:
        return None
    
    if todo.owner_id == user.id:
        return todo
    
    share = db.query(models.TodoShare).filter(
        models.TodoShare.todo_id == todo_id,
        models.TodoShare.shared_with_id == user.id
    ).first()
    
    if share and is_share_valid(share):
        return todo
    
    return None


def get_todo_with_permission(
    db: Session,
    todo_id: int,
    user: models.User,
    required_permission: str = "read_only"
) -> Optional[models.Todo]:
    todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    
    if not todo:
        return None
    
    if todo.owner_id == user.id:
        return todo
    
    share = db.query(models.TodoShare).filter(
        models.TodoShare.todo_id == todo_id,
        models.TodoShare.shared_with_id == user.id
    ).first()
    
    if share and is_share_valid(share):
        if required_permission == "read_write" and share.permission != "read_write":
            return None
        return todo
    
    return None


@router.post("/todos/{todo_id}/share", response_model=schemas.TodoShareOut)
def share_todo_to_user(
    todo_id: int,
    share_data: schemas.TodoShareCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id,
        models.Todo.owner_id == current_user.id
    ).first()
    
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    shared_with_user = db.query(models.User).filter(
        models.User.username == share_data.shared_with_username
    ).first()
    
    if not shared_with_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if shared_with_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot share with yourself")
    
    existing_share = db.query(models.TodoShare).filter(
        models.TodoShare.todo_id == todo_id,
        models.TodoShare.shared_with_id == shared_with_user.id
    ).first()
    
    if existing_share:
        existing_share.permission = validate_permission(share_data.permission)
        existing_share.expires_at = share_data.expires_at
        db.commit()
        db.refresh(existing_share)
        return existing_share
    
    permission = validate_permission(share_data.permission)
    
    new_share = models.TodoShare(
        todo_id=todo_id,
        shared_by_id=current_user.id,
        shared_with_id=shared_with_user.id,
        permission=permission,
        expires_at=share_data.expires_at
    )
    
    db.add(new_share)
    db.commit()
    db.refresh(new_share)
    
    return new_share


@router.post("/todos/{todo_id}/share-link", response_model=schemas.TodoShareLinkOut)
def create_share_link(
    todo_id: int,
    link_data: schemas.TodoShareLinkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id,
        models.Todo.owner_id == current_user.id
    ).first()
    
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    if link_data.is_password_protected and not link_data.password:
        raise HTTPException(
            status_code=400,
            detail="Password is required when password protection is enabled"
        )
    
    permission = validate_permission(link_data.permission)
    
    password_hash = None
    if link_data.is_password_protected and link_data.password:
        password_hash = auth.hash_password(link_data.password)
    
    share_token = str(uuid.uuid4())
    
    new_link = models.TodoShareLink(
        todo_id=todo_id,
        shared_by_id=current_user.id,
        share_token=share_token,
        permission=permission,
        is_password_protected=link_data.is_password_protected,
        password_hash=password_hash,
        expires_at=link_data.expires_at,
        is_active=True,
        views=0
    )
    
    db.add(new_link)
    db.commit()
    db.refresh(new_link)
    
    share_url = build_share_url(request, share_token)
    
    return {
        "id": new_link.id,
        "todo_id": new_link.todo_id,
        "todo_title": todo.title,
        "share_token": new_link.share_token,
        "share_url": share_url,
        "permission": new_link.permission,
        "is_password_protected": new_link.is_password_protected,
        "created_at": new_link.created_at,
        "expires_at": new_link.expires_at,
        "is_active": new_link.is_active,
        "views": new_link.views
    }


@router.get("/todos/{todo_id}/shares", response_model=List[schemas.TodoShareListOut])
def get_todo_shares(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id,
        models.Todo.owner_id == current_user.id
    ).first()
    
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    shares = db.query(models.TodoShare).filter(
        models.TodoShare.todo_id == todo_id
    ).all()
    
    result = []
    for share in shares:
        result.append({
            "id": share.id,
            "todo_id": share.todo_id,
            "todo_title": todo.title,
            "shared_by": share.shared_by,
            "shared_with": share.shared_with,
            "permission": share.permission,
            "created_at": share.created_at,
            "expires_at": share.expires_at
        })
    
    return result


@router.get("/todos/{todo_id}/share-links", response_model=List[schemas.TodoShareLinkOut])
def get_todo_share_links(
    todo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id,
        models.Todo.owner_id == current_user.id
    ).first()
    
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    links = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.todo_id == todo_id
    ).all()
    
    result = []
    for link in links:
        share_url = build_share_url(request, link.share_token)
        result.append({
            "id": link.id,
            "todo_id": link.todo_id,
            "todo_title": todo.title,
            "share_token": link.share_token,
            "share_url": share_url,
            "permission": link.permission,
            "is_password_protected": link.is_password_protected,
            "created_at": link.created_at,
            "expires_at": link.expires_at,
            "is_active": link.is_active,
            "views": link.views
        })
    
    return result


@router.get("/shares/received", response_model=List[schemas.TodoShareListOut])
def get_received_shares(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    shares = db.query(models.TodoShare).filter(
        models.TodoShare.shared_with_id == current_user.id
    ).all()
    
    valid_shares = [s for s in shares if is_share_valid(s)]
    
    result = []
    for share in valid_shares:
        result.append({
            "id": share.id,
            "todo_id": share.todo_id,
            "todo_title": share.todo.title,
            "shared_by": share.shared_by,
            "shared_with": share.shared_with,
            "permission": share.permission,
            "created_at": share.created_at,
            "expires_at": share.expires_at
        })
    
    return result


@router.get("/shares/given", response_model=List[schemas.TodoShareListOut])
def get_given_shares(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    shares = db.query(models.TodoShare).filter(
        models.TodoShare.shared_by_id == current_user.id
    ).all()
    
    result = []
    for share in shares:
        result.append({
            "id": share.id,
            "todo_id": share.todo_id,
            "todo_title": share.todo.title,
            "shared_by": share.shared_by,
            "shared_with": share.shared_with,
            "permission": share.permission,
            "created_at": share.created_at,
            "expires_at": share.expires_at
        })
    
    return result


@router.delete("/shares/{share_id}")
def revoke_share(
    share_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    share = db.query(models.TodoShare).filter(
        models.TodoShare.id == share_id
    ).first()
    
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    
    if share.shared_by_id != current_user.id and share.todo.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to revoke this share")
    
    db.delete(share)
    db.commit()
    
    return {"detail": "Share revoked"}


@router.put("/share-links/{link_id}/deactivate", response_model=schemas.TodoShareLinkOut)
def deactivate_share_link(
    link_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    link = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.id == link_id
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    
    if link.shared_by_id != current_user.id and link.todo.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to deactivate this link")
    
    link.is_active = False
    db.commit()
    db.refresh(link)
    
    share_url = build_share_url(request, link.share_token)
    
    return {
        "id": link.id,
        "todo_id": link.todo_id,
        "todo_title": link.todo.title,
        "share_token": link.share_token,
        "share_url": share_url,
        "permission": link.permission,
        "is_password_protected": link.is_password_protected,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "is_active": link.is_active,
        "views": link.views
    }


@router.delete("/share-links/{link_id}")
def delete_share_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    link = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.id == link_id
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    
    if link.shared_by_id != current_user.id and link.todo.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this link")
    
    db.delete(link)
    db.commit()
    
    return {"detail": "Share link deleted"}


@router.get("/share-links/{share_token}/info")
def get_share_link_info(
    share_token: str,
    db: Session = Depends(get_db)
):
    link = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.share_token == share_token
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    
    if not is_share_link_valid(link):
        raise HTTPException(status_code=410, detail="Share link is expired or deactivated")
    
    return {
        "todo_title": link.todo.title,
        "shared_by": link.shared_by.username,
        "permission": link.permission,
        "is_password_protected": link.is_password_protected,
        "expires_at": link.expires_at
    }


@router.post("/share-links/{share_token}/access", response_model=schemas.ShareInfoOut)
def access_share_link(
    share_token: str,
    access_data: schemas.AccessShareLinkRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    link = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.share_token == share_token
    ).first()
    
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    
    if not is_share_link_valid(link):
        raise HTTPException(status_code=410, detail="Share link is expired or deactivated")
    
    if link.is_password_protected:
        if not access_data.password:
            raise HTTPException(status_code=401, detail="Password required")
        
        if not auth.verify_password(access_data.password, link.password_hash):
            raise HTTPException(status_code=401, detail="Invalid password")
    
    link.views += 1
    db.commit()
    
    return {
        "todo": link.todo,
        "permission": link.permission,
        "share_type": "link",
        "shared_by": link.shared_by
    }
