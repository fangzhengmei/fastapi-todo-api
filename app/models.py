from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime, timedelta
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)

    todos = relationship("Todo", back_populates="owner")
    shares_given = relationship("TodoShare", foreign_keys="TodoShare.shared_by_id", back_populates="shared_by")
    shares_received = relationship("TodoShare", foreign_keys="TodoShare.shared_with_id", back_populates="shared_with")
    share_links = relationship("TodoShareLink", back_populates="shared_by")


class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="not_done")
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="todos")
    shares = relationship("TodoShare", back_populates="todo", cascade="all, delete-orphan")
    share_links = relationship("TodoShareLink", back_populates="todo", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)

    user = relationship("User", backref="refresh_tokens")


class TodoShare(Base):
    __tablename__ = "todo_shares"

    id = Column(Integer, primary_key=True, index=True)
    todo_id = Column(Integer, ForeignKey("todos.id"), nullable=False)
    shared_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shared_with_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    permission = Column(String(20), default="read_only")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    todo = relationship("Todo", back_populates="shares")
    shared_by = relationship("User", foreign_keys=[shared_by_id], back_populates="shares_given")
    shared_with = relationship("User", foreign_keys=[shared_with_id], back_populates="shares_received")


class TodoShareLink(Base):
    __tablename__ = "todo_share_links"

    id = Column(Integer, primary_key=True, index=True)
    todo_id = Column(Integer, ForeignKey("todos.id"), nullable=False)
    shared_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    share_token = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    permission = Column(String(20), default="read_only")
    is_password_protected = Column(Boolean, default=False)
    password_hash = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    views = Column(Integer, default=0)

    todo = relationship("Todo", back_populates="share_links")
    shared_by = relationship("User", back_populates="share_links")
