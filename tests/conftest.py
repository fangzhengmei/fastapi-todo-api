import gc
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

temp_db_files = []


@pytest.fixture(scope="function")
def db_file():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    temp_db_files.append(db_path)
    yield db_path


@pytest.fixture(scope="function")
def test_engine(db_file):
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def TestingSessionLocal(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session(TestingSessionLocal):
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client(TestingSessionLocal):
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function", autouse=True)
def cleanup_after_test():
    yield
    gc.collect()
    time.sleep(0.1)
    for db_path in list(temp_db_files):
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
            temp_db_files.remove(db_path)
        except (PermissionError, OSError):
            pass


def create_test_user(client, username, email, password):
    response = client.post(
        "/register",
        json={
            "username": username,
            "email": email,
            "password": password
        }
    )
    assert response.status_code == 200, f"Failed to create user: {response.json()}"
    return response.json()


def login_test_user(client, email, password):
    response = client.post(
        "/login",
        json={
            "email": email,
            "password": password
        }
    )
    assert response.status_code == 200, f"Failed to login: {response.json()}"
    return response.json()["access_token"]


def create_test_todo(client, access_token, title, description=None):
    response = client.post(
        "/todos/",
        json={
            "title": title,
            "description": description or "Test description"
        },
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200, f"Failed to create todo: {response.json()}"
    return response.json()
