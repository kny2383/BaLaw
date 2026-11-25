# Python 3.12 slim 이미지 사용
FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (PostgreSQL 클라이언트 + C++ 컴파일러)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 고정된 버전(requirements.lock)으로 의존성 설치
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# 애플리케이션 코드 복사
COPY . .

# entrypoint 스크립트 실행 권한 부여
RUN chmod +x entrypoint.sh

# 포트 노출
EXPOSE 8000

# Entrypoint 스크립트 실행
ENTRYPOINT ["./entrypoint.sh"]
