"""암호화해서 저장하는 글 열.

코드는 평문을 읽고 쓰고, DB에는 암호문만 들어간다. 암호화 키는 ENCRYPTION_KEY(Fernet)다.
암호문은 넣을 때마다 달라지므로 이 열로는 SQL에서 값을 비교하거나 검색할 수 없다.
"""
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.services.encryption_service import encryption_service

PREFIX = "enc:v1:"  # 암호문 표시. 이 표시가 없는 값은 암호화 전에 저장된 평문이다.


def encrypt_text(value: str) -> str:
    return PREFIX + encryption_service.cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored  # 마이그레이션 전에 저장된 평문
    return encryption_service.cipher.decrypt(stored[len(PREFIX):].encode("ascii")).decode("utf-8")


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt_text(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt_text(value)
