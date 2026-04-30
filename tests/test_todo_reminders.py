import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app import models, auth

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == "test_reminder@example.com").first()
        if user:
            db.query(models.Todo).filter(models.Todo.owner_id == user.id).delete()
            db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user.id).delete()
            db.delete(user)
            db.commit()
        
        hashed_password = auth.hash_password("testpassword123")
        new_user = models.User(
            username="test_reminder_user",
            email="test_reminder@example.com",
            hashed_password=hashed_password
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        yield new_user
    finally:
        db.query(models.Todo).filter(models.Todo.owner_id == new_user.id).delete()
        db.query(models.RefreshToken).filter(models.RefreshToken.user_id == new_user.id).delete()
        db.delete(new_user)
        db.commit()
        db.close()


@pytest.fixture(scope="module")
def auth_headers(test_user):
    response = client.post("/login", json={
        "email": "test_reminder@example.com",
        "password": "testpassword123"
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTodoReminderCreate:
    def test_create_todo_with_reminder_time(self, auth_headers):
        reminder_time = (datetime.now() + timedelta(hours=1)).isoformat()
        response = client.post("/todos/", json={
            "title": "Test Todo with Reminder",
            "description": "This todo has a reminder",
            "status": "not_done",
            "reminder_time": reminder_time
        }, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Todo with Reminder"
        assert data["reminder_time"] is not None
        assert "reminder_time" in data
    
    def test_create_todo_without_reminder_time(self, auth_headers):
        response = client.post("/todos/", json={
            "title": "Test Todo without Reminder",
            "description": "This todo has no reminder",
            "status": "not_done"
        }, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Todo without Reminder"
        assert data["reminder_time"] is None


class TestTodoReminderUpdate:
    def test_update_todo_add_reminder_time(self, auth_headers):
        response = client.post("/todos/", json={
            "title": "Todo to Update Reminder",
            "description": "Will add reminder later",
            "status": "not_done"
        }, headers=auth_headers)
        assert response.status_code == 200
        todo_id = response.json()["id"]
        
        reminder_time = (datetime.now() + timedelta(days=1)).isoformat()
        update_response = client.put(f"/todos/{todo_id}", json={
            "reminder_time": reminder_time
        }, headers=auth_headers)
        
        assert update_response.status_code == 200
        data = update_response.json()
        assert data["reminder_time"] is not None
    
    def test_update_todo_remove_reminder_time(self, auth_headers):
        reminder_time = (datetime.now() + timedelta(hours=2)).isoformat()
        response = client.post("/todos/", json={
            "title": "Todo to Remove Reminder",
            "description": "Will remove reminder later",
            "status": "not_done",
            "reminder_time": reminder_time
        }, headers=auth_headers)
        assert response.status_code == 200
        todo_id = response.json()["id"]
        assert response.json()["reminder_time"] is not None
        
        update_response = client.put(f"/todos/{todo_id}", json={
            "reminder_time": None
        }, headers=auth_headers)
        
        assert update_response.status_code == 200
        data = update_response.json()
        assert data["reminder_time"] is None


class TestTodoUpcomingReminders:
    def test_get_upcoming_todos_default(self, auth_headers):
        future_time = (datetime.now() + timedelta(hours=2)).isoformat()
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        
        client.post("/todos/", json={
            "title": "Future Reminder Todo",
            "status": "not_done",
            "reminder_time": future_time
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Past Reminder Todo",
            "status": "not_done",
            "reminder_time": past_time
        }, headers=auth_headers)
        
        response = client.get("/todos/upcoming/", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        future_titles = [t["title"] for t in data]
        assert "Future Reminder Todo" in future_titles
        assert "Past Reminder Todo" not in future_titles
    
    def test_get_upcoming_todos_with_time_range(self, auth_headers):
        now = datetime.now()
        time1 = (now + timedelta(hours=1)).isoformat()
        time2 = (now + timedelta(hours=3)).isoformat()
        time3 = (now + timedelta(hours=5)).isoformat()
        
        client.post("/todos/", json={
            "title": "Range Test 1",
            "status": "not_done",
            "reminder_time": time1
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Range Test 2",
            "status": "not_done",
            "reminder_time": time2
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Range Test 3",
            "status": "not_done",
            "reminder_time": time3
        }, headers=auth_headers)
        
        from_time = (now + timedelta(minutes=30)).isoformat()
        to_time = (now + timedelta(hours=4)).isoformat()
        
        response = client.get(
            f"/todos/upcoming/?from_time={from_time}&to_time={to_time}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        titles = [t["title"] for t in data]
        assert "Range Test 1" in titles
        assert "Range Test 2" in titles
        assert "Range Test 3" not in titles
    
    def test_done_todos_not_in_upcoming(self, auth_headers):
        future_time = (datetime.now() + timedelta(hours=1)).isoformat()
        
        response = client.post("/todos/", json={
            "title": "Done Todo with Reminder",
            "status": "not_done",
            "reminder_time": future_time
        }, headers=auth_headers)
        todo_id = response.json()["id"]
        
        client.put(f"/todos/{todo_id}", json={
            "status": "done"
        }, headers=auth_headers)
        
        upcoming_response = client.get("/todos/upcoming/", headers=auth_headers)
        data = upcoming_response.json()
        
        titles = [t["title"] for t in data]
        assert "Done Todo with Reminder" not in titles
    
    def test_todos_without_reminder_not_in_upcoming(self, auth_headers):
        client.post("/todos/", json={
            "title": "No Reminder Todo",
            "status": "not_done"
        }, headers=auth_headers)
        
        response = client.get("/todos/upcoming/", headers=auth_headers)
        data = response.json()
        
        titles = [t["title"] for t in data]
        assert "No Reminder Todo" not in titles