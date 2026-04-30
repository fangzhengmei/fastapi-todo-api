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

    class Config:
        orm_mode = True


# ----------- TODO SCHEMAS -----------

class TodoBase(BaseModel):
    title: str = Field(..., example="Buy groceries")
    description: Optional[str] = Field(None, example="Milk, Bread, Eggs")
    status: Optional[str] = Field("not_done", example="done")
    reminder_time: Optional[datetime] = Field(None, example="2026-05-01T10:00:00")

class TodoCreate(TodoBase):
    pass

class TodoUpdate(BaseModel):
    title: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    reminder_time: Optional[datetime] = Field(None)

class TodoOut(TodoBase):
    id: int
    owner_id: int

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

