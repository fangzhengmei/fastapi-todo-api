import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta

from app.main import app
from app.database import Base
from app.dependencies import get_db
from app import models

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

TEST_USER = {
    "username": "testuser_auto",
    "email": "testuser_auto@example.com",
    "password": "testpassword123"
}

@pytest.fixture(scope="module")
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="module")
def test_user_token(setup_database):
    response = client.post("/register", json=TEST_USER)
    assert response.status_code == 200
    
    login_response = client.post("/login", json={
        "email": TEST_USER["email"],
        "password": TEST_USER["password"]
    })
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    yield token

@pytest.fixture(scope="module")
def auth_headers(test_user_token):
    return {"Authorization": f"Bearer {test_user_token}"}

@pytest.fixture
def create_test_todo(auth_headers):
    def _create_test_todo(title="Test Todo", description="Test description"):
        response = client.post(
            "/todos/",
            json={"title": title, "description": description},
            headers=auth_headers
        )
        assert response.status_code == 200
        return response.json()
    return _create_test_todo

def test_default_auto_clean_days_on_registration(setup_database):
    """Test that new users have default auto-clean days (30 days)"""
    new_user = {
        "username": "newuser_reg",
        "email": "newuser_reg@example.com",
        "password": "testpassword123"
    }
    
    register_response = client.post("/register", json=new_user)
    assert register_response.status_code == 200
    user_data = register_response.json()
    
    assert user_data["trash_auto_clean_days"] == 30

def test_get_auto_clean_days(auth_headers):
    """Test getting the current auto-clean days setting"""
    response = client.get("/users/settings/trash-auto-clean-days", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "trash_auto_clean_days" in data
    assert data["trash_auto_clean_days"] == 30

def test_update_auto_clean_days_valid(auth_headers):
    """Test updating auto-clean days with valid values"""
    response = client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 15},
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["trash_auto_clean_days"] == 15
    assert data["detail"] == "Settings updated successfully"
    
    get_response = client.get("/users/settings/trash-auto-clean-days", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["trash_auto_clean_days"] == 15

def test_update_auto_clean_days_invalid_too_low(auth_headers):
    """Test updating auto-clean days with invalid value (too low)"""
    response = client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 0},
        headers=auth_headers
    )
    assert response.status_code == 422

def test_update_auto_clean_days_invalid_too_high(auth_headers):
    """Test updating auto-clean days with invalid value (too high)"""
    response = client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 400},
        headers=auth_headers
    )
    assert response.status_code == 422

def test_get_current_user_profile_includes_settings(auth_headers):
    """Test that getting current user profile includes auto-clean settings"""
    response = client.get("/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "trash_auto_clean_days" in data
    assert data["trash_auto_clean_days"] == 15

def test_cleanup_no_old_items(auth_headers, create_test_todo):
    """Test cleanup when there are no old items in trash"""
    client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    todo = create_test_todo(title="Fresh Todo", description="Just deleted")
    client.delete(f"/todos/{todo['id']}", headers=auth_headers)
    
    cleanup_response = client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    
    assert data["cleaned_count"] == 0
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    trash_ids = [t["id"] for t in trash_items]
    assert todo["id"] in trash_ids

def test_cleanup_with_old_items(auth_headers, create_test_todo):
    """Test cleanup when there are old items in trash"""
    todo = create_test_todo(title="Old Todo", description="Should be cleaned")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db = TestingSessionLocal()
    db_todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=60)
    db.commit()
    db.close()
    
    client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    cleanup_response = client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    
    assert data["cleaned_count"] >= 1
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    trash_ids = [t["id"] for t in trash_items]
    assert todo_id not in trash_ids

def test_cleanup_respects_user_settings(auth_headers, create_test_todo):
    """Test that cleanup respects the user's auto-clean days setting"""
    todo = create_test_todo(title="Todo for settings test", description="Test")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db = TestingSessionLocal()
    db_todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=20)
    db.commit()
    db.close()
    
    client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 15},
        headers=auth_headers
    )
    
    cleanup_response = client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    assert data["cleaned_count"] >= 1
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id not in trash_ids

def test_cleanup_with_different_settings(auth_headers, create_test_todo):
    """Test that setting auto-clean days higher prevents cleanup"""
    todo = create_test_todo(title="Todo for high setting test", description="Test")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db = TestingSessionLocal()
    db_todo = db.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=20)
    db.commit()
    db.close()
    
    client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    cleanup_response = client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id in trash_ids

def test_cleanup_response_format(auth_headers):
    """Test that cleanup response has the correct format"""
    response = client.post("/todos/trash/cleanup", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "cleaned_count" in data
    assert "message" in data
    assert isinstance(data["cleaned_count"], int)
    assert isinstance(data["message"], str)