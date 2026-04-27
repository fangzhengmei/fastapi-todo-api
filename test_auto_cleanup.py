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

TEST_USER = {
    "username": "testuser_auto",
    "email": "testuser_auto@example.com",
    "password": "testpassword123"
}


@pytest.fixture(scope="module")
def test_db_engine():
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
    
    Base.metadata.create_all(bind=engine)
    
    yield engine, TestingSessionLocal
    
    Base.metadata.drop_all(bind=engine)
    
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]


@pytest.fixture(scope="module")
def db_session(test_db_engine):
    _, TestingSessionLocal = test_db_engine
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def test_client(test_db_engine):
    return TestClient(app)


@pytest.fixture(scope="module")
def test_user_token(test_client):
    response = test_client.post("/register", json=TEST_USER)
    assert response.status_code == 200
    
    login_response = test_client.post("/login", json={
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
def create_test_todo(test_client, auth_headers):
    def _create_test_todo(title="Test Todo", description="Test description"):
        response = test_client.post(
            "/todos/",
            json={"title": title, "description": description},
            headers=auth_headers
        )
        assert response.status_code == 200
        return response.json()
    return _create_test_todo


def test_default_auto_clean_days_on_registration(test_client):
    """Test that new users have default auto-clean days (30 days)"""
    new_user = {
        "username": "newuser_reg",
        "email": "newuser_reg@example.com",
        "password": "testpassword123"
    }
    
    register_response = test_client.post("/register", json=new_user)
    assert register_response.status_code == 200
    user_data = register_response.json()
    
    assert user_data["trash_auto_clean_days"] == 30


def test_get_auto_clean_days(test_client, auth_headers):
    """Test getting the current auto-clean days setting"""
    response = test_client.get("/users/settings/trash-auto-clean-days", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "trash_auto_clean_days" in data
    assert data["trash_auto_clean_days"] == 30


def test_update_auto_clean_days_valid(test_client, auth_headers):
    """Test updating auto-clean days with valid values"""
    response = test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 15},
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["trash_auto_clean_days"] == 15
    assert data["detail"] == "Settings updated successfully"
    
    get_response = test_client.get("/users/settings/trash-auto-clean-days", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["trash_auto_clean_days"] == 15


def test_update_auto_clean_days_invalid_too_low(test_client, auth_headers):
    """Test updating auto-clean days with invalid value (too low)"""
    response = test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 0},
        headers=auth_headers
    )
    assert response.status_code == 422


def test_update_auto_clean_days_invalid_too_high(test_client, auth_headers):
    """Test updating auto-clean days with invalid value (too high)"""
    response = test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 400},
        headers=auth_headers
    )
    assert response.status_code == 422


def test_get_current_user_profile_includes_settings(test_client, auth_headers):
    """Test that getting current user profile includes auto-clean settings"""
    response = test_client.get("/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "trash_auto_clean_days" in data
    assert data["trash_auto_clean_days"] == 15


def test_cleanup_no_old_items(test_client, auth_headers, create_test_todo):
    """Test cleanup when there are no old items in trash"""
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    todo = create_test_todo(title="Fresh Todo", description="Just deleted")
    test_client.delete(f"/todos/{todo['id']}", headers=auth_headers)
    
    cleanup_response = test_client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    
    assert data["cleaned_count"] == 0
    
    trash_response = test_client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    trash_ids = [t["id"] for t in trash_items]
    assert todo["id"] in trash_ids


def test_cleanup_with_old_items(test_client, auth_headers, create_test_todo, db_session):
    """Test cleanup when there are old items in trash"""
    todo = create_test_todo(title="Old Todo", description="Should be cleaned")
    todo_id = todo["id"]
    
    test_client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db_todo = db_session.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=60)
    db_session.commit()
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    cleanup_response = test_client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    
    assert data["cleaned_count"] >= 1
    
    trash_response = test_client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    trash_ids = [t["id"] for t in trash_items]
    assert todo_id not in trash_ids


def test_cleanup_respects_user_settings(test_client, auth_headers, create_test_todo, db_session):
    """Test that cleanup respects the user's auto-clean days setting"""
    todo = create_test_todo(title="Todo for settings test", description="Test")
    todo_id = todo["id"]
    
    test_client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db_todo = db_session.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=20)
    db_session.commit()
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 15},
        headers=auth_headers
    )
    
    cleanup_response = test_client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    data = cleanup_response.json()
    assert data["cleaned_count"] >= 1
    
    trash_response = test_client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id not in trash_ids


def test_cleanup_with_different_settings(test_client, auth_headers, create_test_todo, db_session):
    """Test that setting auto-clean days higher prevents cleanup"""
    todo = create_test_todo(title="Todo for high setting test", description="Test")
    todo_id = todo["id"]
    
    test_client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    db_todo = db_session.query(models.Todo).filter(models.Todo.id == todo_id).first()
    assert db_todo is not None
    db_todo.deleted_at = datetime.utcnow() - timedelta(days=20)
    db_session.commit()
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 30},
        headers=auth_headers
    )
    
    cleanup_response = test_client.post("/todos/trash/cleanup", headers=auth_headers)
    assert cleanup_response.status_code == 200
    
    trash_response = test_client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id in trash_ids


def test_cleanup_response_format(test_client, auth_headers):
    """Test that cleanup response has the correct format"""
    response = test_client.post("/todos/trash/cleanup", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "cleaned_count" in data
    assert "message" in data
    assert isinstance(data["cleaned_count"], int)
    assert isinstance(data["message"], str)


def test_scheduler_status_endpoint(test_client):
    """Test the scheduler status endpoint"""
    response = test_client.get("/health/scheduler")
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert "message" in data
    
    possible_statuses = ["running", "stopped", "not_initialized", "unavailable"]
    assert data["status"] in possible_statuses
    
    if data["status"] == "running":
        assert "jobs" in data
        assert isinstance(data["jobs"], list)


def test_multi_user_isolation_global_cleanup(test_client, db_session, test_db_engine):
    """Test that global cleanup respects each user's individual auto-clean settings"""
    _, TestingSessionLocal = test_db_engine
    
    user1 = {
        "username": "user1_global",
        "email": "user1_global@example.com",
        "password": "password123"
    }
    user2 = {
        "username": "user2_global",
        "email": "user2_global@example.com",
        "password": "password123"
    }
    
    reg1 = test_client.post("/register", json=user1)
    assert reg1.status_code == 200
    user1_id = reg1.json()["id"]
    
    reg2 = test_client.post("/register", json=user2)
    assert reg2.status_code == 200
    user2_id = reg2.json()["id"]
    
    login1 = test_client.post("/login", json={
        "email": user1["email"],
        "password": user1["password"]
    })
    assert login1.status_code == 200
    token1 = login1.json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}
    
    login2 = test_client.post("/login", json={
        "email": user2["email"],
        "password": user2["password"]
    })
    assert login2.status_code == 200
    token2 = login2.json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 10},
        headers=headers1
    )
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 60},
        headers=headers2
    )
    
    todo1 = test_client.post(
        "/todos/",
        json={"title": "User1 Todo", "description": "Test"},
        headers=headers1
    )
    assert todo1.status_code == 200
    todo1_id = todo1.json()["id"]
    
    test_client.delete(f"/todos/{todo1_id}", headers=headers1)
    
    todo2 = test_client.post(
        "/todos/",
        json={"title": "User2 Todo", "description": "Test"},
        headers=headers2
    )
    assert todo2.status_code == 200
    todo2_id = todo2.json()["id"]
    
    test_client.delete(f"/todos/{todo2_id}", headers=headers2)
    
    db_todo1 = db_session.query(models.Todo).filter(models.Todo.id == todo1_id).first()
    db_todo2 = db_session.query(models.Todo).filter(models.Todo.id == todo2_id).first()
    
    assert db_todo1 is not None
    assert db_todo2 is not None
    
    db_todo1.deleted_at = datetime.utcnow() - timedelta(days=30)
    db_todo2.deleted_at = datetime.utcnow() - timedelta(days=30)
    db_session.commit()
    
    from app.routes.todo import auto_cleanup_all_users_trash
    
    cleaned_count = auto_cleanup_all_users_trash(TestingSessionLocal)
    
    assert cleaned_count >= 1
    
    trash1 = test_client.get("/todos/trash/", headers=headers1)
    assert trash1.status_code == 200
    trash1_ids = [t["id"] for t in trash1.json()]
    assert todo1_id not in trash1_ids
    
    trash2 = test_client.get("/todos/trash/", headers=headers2)
    assert trash2.status_code == 200
    trash2_ids = [t["id"] for t in trash2.json()]
    assert todo2_id in trash2_ids


def test_multi_user_different_expiration_scenarios(test_client, db_session, test_db_engine):
    """Test various multi-user scenarios with different expiration dates"""
    _, TestingSessionLocal = test_db_engine
    
    user_a = {
        "username": "user_a_scenarios",
        "email": "user_a_scenarios@example.com",
        "password": "password123"
    }
    user_b = {
        "username": "user_b_scenarios",
        "email": "user_b_scenarios@example.com",
        "password": "password123"
    }
    
    reg_a = test_client.post("/register", json=user_a)
    assert reg_a.status_code == 200
    
    reg_b = test_client.post("/register", json=user_b)
    assert reg_b.status_code == 200
    
    login_a = test_client.post("/login", json={
        "email": user_a["email"],
        "password": user_a["password"]
    })
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}
    
    login_b = test_client.post("/login", json={
        "email": user_b["email"],
        "password": user_b["password"]
    })
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 15},
        headers=headers_a
    )
    
    test_client.put(
        "/users/settings/trash-auto-clean-days",
        json={"trash_auto_clean_days": 45},
        headers=headers_b
    )
    
    old_todo_a = test_client.post(
        "/todos/",
        json={"title": "Old Todo A", "description": "Old"},
        headers=headers_a
    )
    old_todo_a_id = old_todo_a.json()["id"]
    test_client.delete(f"/todos/{old_todo_a_id}", headers=headers_a)
    
    fresh_todo_a = test_client.post(
        "/todos/",
        json={"title": "Fresh Todo A", "description": "Fresh"},
        headers=headers_a
    )
    fresh_todo_a_id = fresh_todo_a.json()["id"]
    test_client.delete(f"/todos/{fresh_todo_a_id}", headers=headers_a)
    
    old_todo_b = test_client.post(
        "/todos/",
        json={"title": "Old Todo B", "description": "Old for B"},
        headers=headers_b
    )
    old_todo_b_id = old_todo_b.json()["id"]
    test_client.delete(f"/todos/{old_todo_b_id}", headers=headers_b)
    
    fresh_todo_b = test_client.post(
        "/todos/",
        json={"title": "Fresh Todo B", "description": "Fresh for B"},
        headers=headers_b
    )
    fresh_todo_b_id = fresh_todo_b.json()["id"]
    test_client.delete(f"/todos/{fresh_todo_b_id}", headers=headers_b)
    
    db_old_a = db_session.query(models.Todo).filter(models.Todo.id == old_todo_a_id).first()
    db_fresh_a = db_session.query(models.Todo).filter(models.Todo.id == fresh_todo_a_id).first()
    db_old_b = db_session.query(models.Todo).filter(models.Todo.id == old_todo_b_id).first()
    db_fresh_b = db_session.query(models.Todo).filter(models.Todo.id == fresh_todo_b_id).first()
    
    db_old_a.deleted_at = datetime.utcnow() - timedelta(days=20)
    db_fresh_a.deleted_at = datetime.utcnow() - timedelta(days=5)
    db_old_b.deleted_at = datetime.utcnow() - timedelta(days=20)
    db_fresh_b.deleted_at = datetime.utcnow() - timedelta(days=5)
    db_session.commit()
    
    from app.routes.todo import auto_cleanup_all_users_trash
    
    cleaned_count = auto_cleanup_all_users_trash(TestingSessionLocal)
    
    assert cleaned_count == 1
    
    trash_a = test_client.get("/todos/trash/", headers=headers_a)
    trash_a_ids = [t["id"] for t in trash_a.json()]
    assert old_todo_a_id not in trash_a_ids
    assert fresh_todo_a_id in trash_a_ids
    
    trash_b = test_client.get("/todos/trash/", headers=headers_b)
    trash_b_ids = [t["id"] for t in trash_b.json()]
    assert old_todo_b_id in trash_b_ids
    assert fresh_todo_b_id in trash_b_ids