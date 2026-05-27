import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.main import app
from app.models.database import Base

# 测试环境覆写
settings.database_url = "sqlite:///file:test_db?mode=memory&cache=shared&uri=true"
settings.jwt_secret = "test-jwt-secret-key-for-pytest-exactly-32-byte"

# 共享内存数据库（:memory: 默认每连接独立）
TEST_DB_URL = "sqlite:///file:test_db?mode=memory&cache=shared&uri=true"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine, autoflush=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


# 替换所有模块的 SessionLocal 为测试版（auth + database + memory 等）
from app.services import auth as auth_svc
from app.models import database as db_module
auth_svc.SessionLocal = TestSession
db_module.SessionLocal = TestSession
app.dependency_overrides[auth_svc.get_db] = override_get_db

# Chat router 也从 auth service 导入 get_db
from app.routers import chat as chat_router
# 已经通过 auth_svc.get_db 覆盖了


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
