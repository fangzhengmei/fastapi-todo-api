import pytest
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app import models, auth

client = TestClient(app)


def format_time_for_url(dt: datetime) -> str:
    return quote(dt.isoformat(), safe='')


@pytest.fixture(scope="module")
def test_boundary_user():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == "test_boundary@example.com").first()
        if user:
            db.query(models.Todo).filter(models.Todo.owner_id == user.id).delete()
            db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user.id).delete()
            db.delete(user)
            db.commit()
        
        hashed_password = auth.hash_password("testpassword123")
        new_user = models.User(
            username="test_boundary_user",
            email="test_boundary@example.com",
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
def auth_headers(test_boundary_user):
    response = client.post("/login", json={
        "email": "test_boundary@example.com",
        "password": "testpassword123"
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTimeRangeBoundary:
    def test_to_time_earlier_than_from_time_returns_400(self, auth_headers):
        now = datetime.now(timezone.utc)
        from_time = (now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        to_time = (now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "Invalid time range" in response.json()["detail"]
        assert "cannot be earlier than" in response.json()["detail"]
    
    def test_to_time_equal_to_from_time_returns_success(self, auth_headers):
        now = datetime.now(timezone.utc)
        target_time = (now + timedelta(hours=1)).replace(microsecond=0, tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Boundary Equal Time Todo",
            "status": "not_done",
            "reminder_time": target_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(target_time)}&to_time={format_time_for_url(target_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        titles = [t["title"] for t in data]
        assert "Boundary Equal Time Todo" in titles
    
    def test_to_time_later_than_from_time_returns_success(self, auth_headers):
        now = datetime.now(timezone.utc)
        from_time = (now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        to_time = (now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        reminder_time = (now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Boundary Valid Range Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        titles = [t["title"] for t in data]
        assert "Boundary Valid Range Todo" in titles


class TestTimezoneHandling:
    def test_create_with_timezone_aware_time_converts_to_utc(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        beijing_time = (utc_now + timedelta(hours=8)).replace(tzinfo=timezone(timedelta(hours=8)))
        
        response = client.post("/todos/", json={
            "title": "Timezone Test Todo",
            "status": "not_done",
            "reminder_time": beijing_time.isoformat()
        }, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["reminder_time"] is not None
        
        stored_time = datetime.fromisoformat(data["reminder_time"].replace("Z", "+00:00"))
        expected_utc = beijing_time.astimezone(timezone.utc).replace(tzinfo=None)
        
        assert abs((stored_time.replace(tzinfo=None) - expected_utc).total_seconds()) < 1
    
    def test_create_with_naive_time_remains_unchanged(self, auth_headers):
        naive_time = datetime(2026, 5, 1, 10, 0, 0)
        
        response = client.post("/todos/", json={
            "title": "Naive Time Todo",
            "status": "not_done",
            "reminder_time": naive_time.isoformat()
        }, headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["reminder_time"] is not None
        
        stored_time = datetime.fromisoformat(data["reminder_time"].replace("Z", "+00:00"))
        assert stored_time.replace(tzinfo=None) == naive_time
    
    def test_query_with_mixed_timezones_works_consistently(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        
        beijing_offset = timezone(timedelta(hours=8))
        beijing_time = (utc_now + timedelta(hours=10)).replace(tzinfo=beijing_offset)
        
        client.post("/todos/", json={
            "title": "Beijing Time Todo",
            "status": "not_done",
            "reminder_time": beijing_time.isoformat()
        }, headers=auth_headers)
        
        utc_from = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        utc_to = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(utc_from)}&to_time={format_time_for_url(utc_to)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        titles = [t["title"] for t in data]
        assert "Beijing Time Todo" in titles
    
    def test_update_with_timezone_aware_time_converts_to_utc(self, auth_headers):
        response = client.post("/todos/", json={
            "title": "Update Timezone Todo",
            "status": "not_done"
        }, headers=auth_headers)
        todo_id = response.json()["id"]
        
        utc_now = datetime.now(timezone.utc)
        tokyo_time = (utc_now + timedelta(hours=9)).replace(tzinfo=timezone(timedelta(hours=9)))
        
        update_response = client.put(f"/todos/{todo_id}", json={
            "reminder_time": tokyo_time.isoformat()
        }, headers=auth_headers)
        
        assert update_response.status_code == 200
        data = update_response.json()
        assert data["reminder_time"] is not None
        
        stored_time = datetime.fromisoformat(data["reminder_time"].replace("Z", "+00:00"))
        expected_utc = tokyo_time.astimezone(timezone.utc).replace(tzinfo=None)
        
        assert abs((stored_time.replace(tzinfo=None) - expected_utc).total_seconds()) < 1


class TestEdgeCases:
    def test_only_from_time_provided(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Only From Time Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        titles = [t["title"] for t in data]
        assert "Only From Time Todo" in titles
    
    def test_only_to_time_provided(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        to_time = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Only To Time Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        titles = [t["title"] for t in data]
        assert "Only To Time Todo" in titles
    
    def test_no_time_params_uses_default(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        future_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        past_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Default Time Todo",
            "status": "not_done",
            "reminder_time": future_time.isoformat()
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Past Default Todo",
            "status": "not_done",
            "reminder_time": past_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get("/todos/upcoming/", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        titles = [t["title"] for t in data]
        assert "Default Time Todo" in titles
        assert "Past Default Todo" not in titles