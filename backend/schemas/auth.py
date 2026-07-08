from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountCreate(BaseModel):
    name: str
    api_key: str
    secret_key: str
    passphrase: str | None = None
    trade_mode: str = "demo"


class AccountUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    secret_key: str | None = None
    passphrase: str | None = None
    trade_mode: str | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
