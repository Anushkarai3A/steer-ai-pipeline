from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import APIError, bad_request
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.auth import LoginIn, TokenOut, UserOut
from app.core.ids import new_id

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise APIError(401, "Incorrect email or password.", "invalid_credentials")
    token = create_access_token(user.id, user.role)
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/register", response_model=UserOut)
def register(body: LoginIn, db: Session = Depends(get_db)) -> User:
    """Open registration creates an *editor* account.

    Reviewer (doctor) permissions are only granted server-side by an admin —
    never by the client.
    """
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise bad_request("An account with that email already exists.")
    if len(body.password) < 8:
        raise APIError(422, "Password must be at least 8 characters.", "weak_password")
    name = email.split("@")[0].replace(".", " ").title()
    user = User(
        id=new_id("usr"),
        email=email,
        name=name,
        role=UserRole.editor.value,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
