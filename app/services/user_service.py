from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app import models, schemas, auth


class UserService:
    @staticmethod
    def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
        return db.query(models.User).filter(models.User.username == username).first()

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
        return db.query(models.User).filter(models.User.email == email).first()

    @staticmethod
    def register_user(db: Session, user_data: schemas.UserCreate) -> models.User:
        existing_username = UserService.get_user_by_username(db, user_data.username)
        existing_email = UserService.get_user_by_email(db, user_data.email)

        if existing_username:
            raise HTTPException(status_code=400, detail="Username already exists")
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")

        hashed_password = auth.hash_password(user_data.password)
        new_user = models.User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> models.User:
        user = UserService.get_user_by_email(db, email)

        if not user or not auth.verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        return user

    @staticmethod
    def get_refresh_token_entry(db: Session, token: str) -> Optional[models.RefreshToken]:
        return db.query(models.RefreshToken).filter_by(token=token).first()

    @staticmethod
    def logout_user(db: Session, refresh_token: str) -> None:
        token_entry = UserService.get_refresh_token_entry(db, refresh_token)

        if not token_entry or token_entry.is_revoked:
            raise HTTPException(status_code=401, detail="Token already invalid or not found")

        token_entry.is_revoked = True
        db.commit()
