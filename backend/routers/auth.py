from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.log import OperationLog
from schemas.auth import LoginRequest, TokenResponse, ChangePasswordRequest
from services.auth_service import hash_password, verify_password, create_access_token
from middleware.auth import get_current_user
from config import LOGIN_MAX_ATTEMPTS, LOGIN_LOCKOUT_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=423, detail="账户已锁定，请稍后再试")

    if not verify_password(body.password, user.password_hash):
        user.login_attempts += 1
        if user.login_attempts >= LOGIN_MAX_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc)
            try:
                user.locked_until = user.locked_until.replace(
                    minute=user.locked_until.minute + LOGIN_LOCKOUT_MINUTES
                )
            except ValueError:
                user.locked_until = user.locked_until.replace(
                    hour=user.locked_until.hour + 1,
                    minute=(user.locked_until.minute + LOGIN_LOCKOUT_MINUTES) % 60,
                )
        db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user.login_attempts = 0
    user.locked_until = None
    db.commit()

    log = OperationLog(
        user_id=user.id,
        action="login",
        target_type="system",
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token)


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}


@router.put("/password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="旧密码不正确")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要6位")

    user.password_hash = hash_password(body.new_password)
    db.commit()

    return {"message": "密码修改成功"}
