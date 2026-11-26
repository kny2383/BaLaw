from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Index, false
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.encrypted_text import EncryptedText

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_complaint_id_id", "complaint_id", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)

    # 메시지 정보
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    # 대화 글은 암호화해서 저장한다 (S03). SQL에서 내용을 비교할 수 없으므로 걸러 낼 기준은 따로 열로 둔다.
    content = Column(EncryptedText, nullable=False)  # 메시지 내용
    reason = Column(EncryptedText, nullable=True)
    # 화면이 첫 질문을 받으려고 대신 보낸 고정 문장인가. 지금은 그 문장을 저장하지 않으므로 새 행은 늘 거짓이다.
    # 예전에 저장된 행에는 남아 있어, 암호화 마이그레이션이 표시하고 대화 기록 화면에서 뺀다.
    is_internal = Column(Boolean, nullable=False, default=False, server_default=false())

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    complaint = relationship("Complaint", back_populates="chat_messages")
