from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

# ----------- USER SCHEMAS -----------

class UserBase(BaseModel):
    username: str = Field(..., example="johndoe")
    email: EmailStr = Field(..., example="johndoe@example.com")

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, example="strongpassword123")

class UserLogin(BaseModel):
    email: EmailStr = Field(..., example="user@example.com")
    password: str = Field(..., example="strongpassword123")

class UserOut(UserBase):
    id: int

    class Config:
        orm_mode = True


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


# ----------- SHARE SCHEMAS -----------

class TodoShareBase(BaseModel):
    permission: str = Field("read_only", example="read_only")
    expires_at: Optional[datetime] = Field(None, description="Expiration time for the share")

class TodoShareCreate(TodoShareBase):
    shared_with_username: str = Field(..., example="johndoe")

class TodoShareOut(TodoShareBase):
    id: int
    todo_id: int
    shared_by: UserOut
    shared_with: UserOut
    created_at: datetime

    class Config:
        orm_mode = True

class TodoShareListOut(BaseModel):
    id: int
    todo_id: int
    todo_title: str
    shared_by: UserOut
    shared_with: UserOut
    permission: str
    created_at: datetime
    expires_at: Optional[datetime]

    class Config:
        orm_mode = True


# ----------- SHARE LINK SCHEMAS -----------

class TodoShareLinkBase(BaseModel):
    permission: str = Field("read_only", example="read_only")
    expires_at: Optional[datetime] = Field(None, description="Expiration time for the link")

class TodoShareLinkCreate(TodoShareLinkBase):
    is_password_protected: bool = Field(False, example=False)
    password: Optional[str] = Field(None, min_length=6, example="sharepass123")

class TodoShareLinkOut(BaseModel):
    id: int
    todo_id: int
    todo_title: str
    share_token: str
    share_url: str
    permission: str
    is_password_protected: bool
    created_at: datetime
    expires_at: Optional[datetime]
    is_active: bool
    views: int

    class Config:
        orm_mode = True

class AccessShareLinkRequest(BaseModel):
    password: Optional[str] = Field(None, example="sharepass123")

class ShareInfoOut(BaseModel):
    todo: TodoOut
    permission: str
    share_type: str
    shared_by: Optional[UserOut] = None

