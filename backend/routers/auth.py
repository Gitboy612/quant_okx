from datetime import datetime, timezone
from ipaddress import ip_address
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from models.user import User
from models.log import OperationLog
from schemas.auth import LoginRequest, TokenResponse, ChangePasswordRequest, InitialSetupRequest
from services.auth_service import hash_password, verify_password, create_access_token
from middleware.auth import get_current_user
from config import LOGIN_MAX_ATTEMPTS, LOGIN_LOCKOUT_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    return {"setup_required": db.query(User.id).first() is None}


@router.post("/setup", response_model=TokenResponse)
def initial_setup(body: InitialSetupRequest, request: Request, db: Session = Depends(get_db)):
    """仅允许从本机完成一次性管理员初始化。"""
    try:
        local_request = ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        local_request = False
    if not local_request:
        raise HTTPException(status_code=403, detail="首次设置仅允许在服务器本机进行")
    if db.query(User.id).first() is not None:
        raise HTTPException(status_code=409, detail="管理员已设置，请直接登录")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")
    if len(body.password) < 8 or len(body.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码至少 8 个字符，且不超过 72 字节")

    user = User(username="admin", password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="管理员已设置，请直接登录")
    return TokenResponse(access_token=create_access_token({"sub": str(user.id), "username": user.username}))


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

    if len(body.new_password) < 8 or len(body.new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码至少 8 个字符，且不超过 72 字节")

    user.password_hash = hash_password(body.new_password)
    db.commit()

    return {"message": "密码修改成功"}
