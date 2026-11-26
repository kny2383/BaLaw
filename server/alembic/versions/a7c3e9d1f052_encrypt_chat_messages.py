"""Encrypt chat message text

Revision ID: a7c3e9d1f052
Revises: 8c1f2a3b4d5e
Create Date: 2026-11-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d1f052'
down_revision: Union[str, Sequence[str], None] = '8c1f2a3b4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 이 마이그레이션을 쓸 때의 값을 그대로 적어 둔다. 앱 코드의 값이 나중에 바뀌어도 이 변환은 같아야 한다.
PREFIX = "enc:v1:"
INTERNAL_MESSAGES = (
    "위 사건 개요를 기반으로, 이어서 질문을 해 주세요.",
    "위 사건 개요를 기반으로, 고소장 작성을 위해 필요한 정보를 단계적으로 질문해 주세요.",
)
BATCH = 500


def _cipher():
    from cryptography.fernet import Fernet

    from app.config import settings

    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_rows(conn) -> int:
    """평문으로 저장된 대화 글을 암호화하고, 화면이 대신 보낸 고정 문장에 표시를 남긴다. 바꾼 행 수를 돌려준다.

    이미 암호화된 행은 건드리지 않으므로 중간에 멈춰도 다시 실행하면 이어진다.
    """
    cipher = _cipher()

    def enc(value):
        if value is None or value.startswith(PREFIX):
            return value
        return PREFIX + cipher.encrypt(value.encode("utf-8")).decode("ascii")

    changed, last_id = 0, 0
    while True:
        rows = conn.execute(
            sa.text("SELECT id, role, content, reason FROM chat_messages WHERE id > :last ORDER BY id LIMIT :n"),
            {"last": last_id, "n": BATCH},
        ).fetchall()
        if not rows:
            return changed
        for row in rows:
            last_id = row.id
            plain_content = not (row.content or "").startswith(PREFIX)
            plain_reason = row.reason is not None and not row.reason.startswith(PREFIX)
            if not plain_content and not plain_reason:
                continue
            params = {"id": row.id, "content": enc(row.content), "reason": enc(row.reason)}
            if plain_content:
                # 암호화하면 내용으로 가릴 수 없게 되므로 지금 표시한다.
                params["internal"] = row.role == "user" and (row.content or "").strip() in INTERNAL_MESSAGES
                conn.execute(sa.text(
                    "UPDATE chat_messages SET content = :content, reason = :reason, is_internal = :internal WHERE id = :id"
                ), params)
            else:
                conn.execute(sa.text("UPDATE chat_messages SET reason = :reason WHERE id = :id"), params)
            changed += 1


def decrypt_rows(conn) -> int:
    cipher = _cipher()

    def dec(value):
        if value is None or not value.startswith(PREFIX):
            return value
        return cipher.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")

    changed, last_id = 0, 0
    while True:
        rows = conn.execute(
            sa.text("SELECT id, content, reason FROM chat_messages WHERE id > :last ORDER BY id LIMIT :n"),
            {"last": last_id, "n": BATCH},
        ).fetchall()
        if not rows:
            return changed
        for row in rows:
            last_id = row.id
            conn.execute(sa.text("UPDATE chat_messages SET content = :content, reason = :reason WHERE id = :id"),
                         {"id": row.id, "content": dec(row.content), "reason": dec(row.reason)})
            changed += 1


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'chat_messages' not in inspector.get_table_names():
        return

    columns = [col['name'] for col in inspector.get_columns('chat_messages')]
    if 'is_internal' not in columns:
        op.add_column('chat_messages',
                      sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.false()))
    encrypt_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'chat_messages' not in inspector.get_table_names():
        return

    decrypt_rows(conn)
    columns = [col['name'] for col in inspector.get_columns('chat_messages')]
    if 'is_internal' in columns:
        op.drop_column('chat_messages', 'is_internal')
