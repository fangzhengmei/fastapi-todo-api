import pytest
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app import models, auth
from app.time_utils import (
    normalize_to_utc_naive,
    get_utc_now_naive,
    validate_time_range
)

client = TestClient(app)


def format_time_for_url(dt: datetime) -> str:
    return quote(dt.isoformat(), safe='')


@pytest.fixture(scope="module")
def test_policy_user():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == "test_policy@example.com").first()
        if user:
            db.query(models.Todo).filter(models.Todo.owner_id == user.id).delete()
            db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user.id).delete()
            db.delete(user)
            db.commit()
        
        hashed_password = auth.hash_password("testpassword123")
        new_user = models.User(
            username="test_policy_user",
            email="test_policy@example.com",
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
def auth_headers(test_policy_user):
    response = client.post("/login", json={
        "email": "test_policy@example.com",
        "password": "testpassword123"
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTimeUtilsUnit:
    def test_normalize_to_utc_naive_with_utc_timezone(self):
        utc_time = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = normalize_to_utc_naive(utc_time)
        assert result.tzinfo is None
        assert result == datetime(2026, 5, 1, 10, 0, 0)
    
    def test_normalize_to_utc_naive_with_positive_offset(self):
        beijing_time = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        result = normalize_to_utc_naive(beijing_time)
        assert result.tzinfo is None
        assert result == datetime(2026, 5, 1, 10, 0, 0)
    
    def test_normalize_to_utc_naive_with_negative_offset(self):
        ny_time = datetime(2026, 5, 1, 6, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
        result = normalize_to_utc_naive(ny_time)
        assert result.tzinfo is None
        assert result == datetime(2026, 5, 1, 10, 0, 0)
    
    def test_normalize_to_utc_naive_with_naive_time(self):
        naive_time = datetime(2026, 5, 1, 10, 0, 0)
        result = normalize_to_utc_naive(naive_time)
        assert result.tzinfo is None
        assert result == naive_time
    
    def test_normalize_to_utc_naive_with_none(self):
        result = normalize_to_utc_naive(None)
        assert result is None
    
    def test_get_utc_now_naive(self):
        result = get_utc_now_naive()
        assert result.tzinfo is None
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((result - utc_now).total_seconds()) < 1
    
    def test_validate_time_range_valid(self):
        from_time = datetime(2026, 5, 1, 10, 0, 0)
        to_time = datetime(2026, 5, 1, 12, 0, 0)
        result_from, result_to = validate_time_range(from_time, to_time)
        assert result_from == from_time
        assert result_to == to_time
    
    def test_validate_time_range_equal(self):
        time_point = datetime(2026, 5, 1, 10, 0, 0)
        result_from, result_to = validate_time_range(time_point, time_point)
        assert result_from == time_point
        assert result_to == time_point
    
    def test_validate_time_range_invalid_too_earlier(self):
        from_time = datetime(2026, 5, 1, 12, 0, 0)
        to_time = datetime(2026, 5, 1, 10, 0, 0)
        with pytest.raises(ValueError, match="Invalid time range"):
            validate_time_range(from_time, to_time)
    
    def test_validate_time_range_with_timezone_conversion(self):
        from_time = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        to_time = datetime(2026, 5, 1, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        result_from, result_to = validate_time_range(from_time, to_time)
        assert result_from.tzinfo is None
        assert result_to.tzinfo is None
        assert result_from == datetime(2026, 5, 1, 10, 0, 0)
        assert result_to == datetime(2026, 5, 1, 12, 0, 0)


class TestTimePolicyIntegration:
    def test_create_with_different_timezones_same_utc(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        
        utc_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        beijing_time = (utc_now + timedelta(hours=10)).replace(tzinfo=timezone(timedelta(hours=8)))
        
        response1 = client.post("/todos/", json={
            "title": "UTC Time Todo",
            "status": "not_done",
            "reminder_time": utc_time.isoformat()
        }, headers=auth_headers)
        
        response2 = client.post("/todos/", json={
            "title": "Beijing Time Todo",
            "status": "not_done",
            "reminder_time": beijing_time.isoformat()
        }, headers=auth_headers)
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        stored1 = response1.json()["reminder_time"]
        stored2 = response2.json()["reminder_time"]
        
        assert stored1 == stored2
    
    def test_query_with_different_timezones_same_result(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        reminder_utc = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        
        response = client.post("/todos/", json={
            "title": "Consistent Query Todo",
            "status": "not_done",
            "reminder_time": reminder_utc.isoformat()
        }, headers=auth_headers)
        assert response.status_code == 200
        
        from_utc = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        to_utc = (utc_now + timedelta(hours=5)).replace(tzinfo=timezone.utc)
        
        from_beijing = (utc_now + timedelta(hours=11)).replace(tzinfo=timezone(timedelta(hours=8)))
        to_beijing = (utc_now + timedelta(hours=13)).replace(tzinfo=timezone(timedelta(hours=8)))
        
        response1 = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_utc)}&to_time={format_time_for_url(to_utc)}",
            headers=auth_headers
        )
        
        response2 = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_beijing)}&to_time={format_time_for_url(to_beijing)}",
            headers=auth_headers
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        titles1 = [t["title"] for t in response1.json()]
        titles2 = [t["title"] for t in response2.json()]
        
        assert "Consistent Query Todo" in titles1
        assert "Consistent Query Todo" in titles2


class TestBoundaryConditions:
    def test_to_time_slightly_earlier_than_from_time(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=2, microseconds=100)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "Invalid time range" in response.json()["detail"]
    
    def test_to_time_slightly_later_than_from_time(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=2, microseconds=100)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=2, microseconds=50)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Slight Edge Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Slight Edge Todo" in titles
    
    def test_exact_boundary_inclusive(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        exact_time = (utc_now + timedelta(hours=3)).replace(microsecond=0, tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Exact Boundary Todo",
            "status": "not_done",
            "reminder_time": exact_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(exact_time)}&to_time={format_time_for_url(exact_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Exact Boundary Todo" in titles
    
    def test_just_outside_upper_boundary(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=4, microseconds=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Just Outside Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Just Outside Todo" not in titles
    
    def test_just_inside_lower_boundary(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=2, microseconds=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Just Inside Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Just Inside Todo" in titles


class TestMixedTimezoneScenarios:
    def test_create_naive_query_with_timezone(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        naive_time = (utc_now + timedelta(hours=5)).replace(tzinfo=None)
        
        client.post("/todos/", json={
            "title": "Naive Create Todo",
            "status": "not_done",
            "reminder_time": naive_time.isoformat()
        }, headers=auth_headers)
        
        from_beijing = (utc_now + timedelta(hours=13)).replace(tzinfo=timezone(timedelta(hours=8)))
        to_beijing = (utc_now + timedelta(hours=14)).replace(tzinfo=timezone(timedelta(hours=8)))
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_beijing)}&to_time={format_time_for_url(to_beijing)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Naive Create Todo" in titles
    
    def test_create_with_timezone_query_naive(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        beijing_time = (utc_now + timedelta(hours=13)).replace(tzinfo=timezone(timedelta(hours=8)))
        
        client.post("/todos/", json={
            "title": "Timezone Create Todo",
            "status": "not_done",
            "reminder_time": beijing_time.isoformat()
        }, headers=auth_headers)
        
        naive_from = (utc_now + timedelta(hours=4)).replace(tzinfo=None)
        naive_to = (utc_now + timedelta(hours=6)).replace(tzinfo=None)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(naive_from)}&to_time={format_time_for_url(naive_to)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Timezone Create Todo" in titles


class TestErrorScenarios:
    def test_invalid_time_range_error_message_contains_details(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=5)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Invalid time range" in detail
        assert "cannot be earlier than" in detail
        
        from_time_naive = from_time.replace(tzinfo=None)
        to_time_naive = to_time.replace(tzinfo=None)
        assert from_time_naive.isoformat() in detail
        assert to_time_naive.isoformat() in detail
    
    def test_invalid_time_range_with_timezone_conversion(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_beijing = (utc_now + timedelta(hours=13)).replace(tzinfo=timezone(timedelta(hours=8)))
        to_utc = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_beijing)}&to_time={format_time_for_url(to_utc)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "Invalid time range" in response.json()["detail"]