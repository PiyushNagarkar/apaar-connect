from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str
    password: str


class UserSummary(BaseModel):
    id: str
    email: str
    role: str
    institution_id: Optional[str] = None
    student_id: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes (short expiry)
    user: UserSummary


class UserProfileResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    role: str
    institution_id: Optional[str] = None
    student_id: Optional[str] = None
    permissions: List[str]
