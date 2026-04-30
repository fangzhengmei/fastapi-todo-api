from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from app import schemas, models, auth
from app.dependencies import get_db
from app.services import UserService

router = APIRouter(tags=["Users"])


# -------- Register -------- #
@router.post("/register", response_model=schemas.UserOut)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return UserService.register_user(db, user)

# -------- Login -------- #
@router.post("/login", response_model=schemas.Token)
def login(user_login: schemas.UserLogin, db: Session = Depends(get_db)):
    user = UserService.authenticate_user(db, user_login.email, user_login.password)

    access_token = auth.create_access_token(data={"sub": user.username})
    refresh_token = auth.create_refresh_token_db(user=user, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

# --------- Refresh Token ----------#
@router.post("/refresh-token", response_model=schemas.Token)
def refresh_token(req: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    username = auth.verify_refresh_token_db(req.refresh_token, db)
    user = UserService.get_user_by_username(db, username)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access_token = auth.create_access_token(data={"sub": username})
    new_refresh_token = auth.create_refresh_token_db(user=user, db=db)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

# --------- Logout ----------#
@router.post("/logout")
def logout(req: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    UserService.logout_user(db, req.refresh_token)
    return {"detail": "Logged out successfully"}
