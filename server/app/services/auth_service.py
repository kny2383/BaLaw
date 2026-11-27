from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from app.config import settings
from app.schemas.auth import TokenData

# 토큰 종류. 토큰 안의 type 값이다.
ACCESS = "access"
REFRESH = "refresh"

# 비밀번호 해싱
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 확인"""
    # 72바이트 제한
    plain_password = plain_password[:72]
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """비밀번호 해싱"""
    # 72바이트 제한
    password = password[:72]
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": ACCESS})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: timedelta = None):
    """JWT 리프레시 토큰 생성"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": REFRESH})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt

def verify_token(token: str, expected_type: str) -> TokenData:
    """토큰을 검증한다. 서명과 만료가 맞아도 종류(type)가 expected_type과 다르면 받지 않는다.

    액세스 토큰(30분)과 리프레시 토큰(7일)을 서로의 자리에 쓸 수 없게 한다.
    종류가 적히지 않은 토큰(이 검사를 넣기 전에 발급된 것)도 받지 않는다. 다시 로그인해야 한다.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")

        if email is None or payload.get("type") != expected_type:
            return None

        return TokenData(email=email)
    except JWTError:
        return None
