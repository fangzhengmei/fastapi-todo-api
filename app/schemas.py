from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

# ----------- USER SCHEMAS -----------

class UserBase(BaseModel):
    username: str = Field(..., example="johndoe")
    email: EmailStr = Field(..., example="johndoe@example.com")  # ✅ Add email here

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, example="strongpassword123")

class UserLogin(BaseModel):
    email: EmailStr = Field(..., example="user@example.com")  # ✅ Rename field for clarity
    password: str = Field(..., example="strongpassword123")

class UserOut(UserBase):  # Inherits username and email
    id: int
    trash_auto_clean_days: int = 30

    class Config:
        orm_mode = True


class UserSettingsUpdate(BaseModel):
    trash_auto_clean_days: int = Field(..., ge=1, le=365, example=30)


class TrashCleanupResult(BaseModel):
    cleaned_count: int
    message: str


# ----------- TODO SCHEMAS -----------

class TodoBase(BaseModel):
    title: str = Field(..., example="Buy groceries")
    description: Optional[str] = Field(None, example="Milk, Bread, Eggs")
    status: Optional[str] = Field("not_done", example="done")

class TodoCreate(TodoBase):
    pass

class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class TodoOut(TodoBase):
    id: int
    owner_id: int
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# ----------- TOKEN SCHEMAS -----------

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

