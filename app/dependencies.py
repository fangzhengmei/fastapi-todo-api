from app.database import SessionLocal
from sqlalchemy.orm import Session
from fastapi import Depends, Header, HTTPException
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import re

from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


@dataclass
class AccessContext:
    user: Optional[models.User] = None
    share_link: Optional[models.TodoShareLink] = None
    has_bearer_token: bool = False
    has_share_token: bool = False
    
    @property
    def has_credentials(self) -> bool:
        return self.has_bearer_token or self.has_share_token


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_user_share_valid(share: models.TodoShare) -> bool:
    if share.expires_at and share.expires_at < datetime.utcnow():
        return False
    return True


def is_share_link_valid(share_link: models.TodoShareLink) -> bool:
    if not share_link.is_active:
        return False
    if share_link.expires_at and share_link.expires_at < datetime.utcnow():
        return False
    return True


def extract_bearer_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization:
        return None
    match = re.match(r"^Bearer\s+(.+)$", authorization, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def get_share_link_from_token(
    db: Session,
    share_token: str,
    share_password: Optional[str] = None
) -> Optional[models.TodoShareLink]:
    from app import auth
    
    link = db.query(models.TodoShareLink).filter(
        models.TodoShareLink.share_token == share_token
    ).first()
    
    if not link:
        return None
    
    if not is_share_link_valid(link):
        return None
    
    if link.is_password_protected:
        if not share_password:
            return None
        if not auth.verify_password(share_password, link.password_hash):
            return None
    
    return link


def get_current_user_from_token(
    token: str,
    db: Session
) -> Optional[models.User]:
    from app import auth
    
    try:
        return auth.get_current_user(token=token, db=db)
    except HTTPException:
        return None


def get_access_context(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_share_token: Optional[str] = Header(None, alias="X-Share-Token"),
    x_share_password: Optional[str] = Header(None, alias="X-Share-Password"),
) -> AccessContext:
    context = AccessContext()
    
    if authorization:
        context.has_bearer_token = True
        bearer_token = extract_bearer_token(authorization)
        if bearer_token:
            context.user = get_current_user_from_token(bearer_token, db)
    
    if x_share_token:
        context.has_share_token = True
        context.share_link = get_share_link_from_token(db, x_share_token, x_share_password)
    
    return context
