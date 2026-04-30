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


class TestDefaultParameterScenarios:
    def test_scenario1_both_default(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        future_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        past_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario1 Future Todo",
            "status": "not_done",
            "reminder_time": future_time.isoformat()
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Scenario1 Past Todo",
            "status": "not_done",
            "reminder_time": past_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get("/todos/upcoming/", headers=auth_headers)
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario1 Future Todo" in titles
        assert "Scenario1 Past Todo" not in titles
    
    def test_scenario2_only_from_time(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        reminder_in = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        reminder_out = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario2 In Todo",
            "status": "not_done",
            "reminder_time": reminder_in.isoformat()
        }, headers=auth_headers)
        
        client.post("/todos/", json={
            "title": "Scenario2 Out Todo",
            "status": "not_done",
            "reminder_time": reminder_out.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario2 In Todo" in titles
        assert "Scenario2 Out Todo" not in titles
    
    def test_scenario3_only_to_time_not_error(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        to_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_scenario3_only_to_time_returns_empty(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        future_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        to_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario3 Future Todo",
            "status": "not_done",
            "reminder_time": future_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario3 Future Todo" not in titles
    
    def test_scenario4_both_provided_valid(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        reminder_in = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario4 In Todo",
            "status": "not_done",
            "reminder_time": reminder_in.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario4 In Todo" in titles
    
    def test_scenario4_both_provided_invalid_returns_error(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "Invalid time range" in response.json()["detail"]


class TestValidateTimeRangeUnit:
    def test_both_provided_invalid_raises(self):
        from_time = datetime(2026, 5, 1, 12, 0, 0)
        to_time = datetime(2026, 5, 1, 10, 0, 0)
        
        with pytest.raises(ValueError, match="Invalid time range"):
            validate_time_range(from_time, to_time)
    
    def test_only_to_time_provided_too_early_no_error(self):
        from_time = None
        to_time = datetime(2026, 5, 1, 10, 0, 0)
        default_from = datetime(2026, 5, 1, 12, 0, 0)
        
        result_from, result_to = validate_time_range(from_time, to_time, default_from)
        
        assert result_from == default_from
        assert result_to == to_time
    
    def test_only_from_time_provided_no_error(self):
        from_time = datetime(2026, 5, 1, 12, 0, 0)
        to_time = None
        
        result_from, result_to = validate_time_range(from_time, to_time)
        
        assert result_from == from_time
        assert result_to is None
    
    def test_both_default_no_error(self):
        default_from = datetime(2026, 5, 1, 12, 0, 0)
        
        result_from, result_to = validate_time_range(None, None, default_from)
        
        assert result_from == default_from
        assert result_to is None
    
    def test_both_provided_valid_returns_tuple(self):
        from_time = datetime(2026, 5, 1, 10, 0, 0)
        to_time = datetime(2026, 5, 1, 12, 0, 0)
        
        result_from, result_to = validate_time_range(from_time, to_time)
        
        assert result_from == from_time
        assert result_to == to_time


class TestScenario3SubScenarios:
    def test_scenario3a_to_time_greater_than_current(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        to_time = (utc_now + timedelta(hours=5)).replace(tzinfo=timezone.utc)
        reminder_time = (utc_now + timedelta(hours=2)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario3a Todo",
            "status": "not_done",
            "reminder_time": reminder_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario3a Todo" in titles
    
    def test_scenario3c_to_time_less_than_current_no_error(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        to_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_scenario3c_to_time_less_than_current_returns_empty(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        future_time = (utc_now + timedelta(hours=1)).replace(tzinfo=timezone.utc)
        to_time = (utc_now - timedelta(hours=1)).replace(tzinfo=timezone.utc)
        
        client.post("/todos/", json={
            "title": "Scenario3c Future Todo",
            "status": "not_done",
            "reminder_time": future_time.isoformat()
        }, headers=auth_headers)
        
        response = client.get(
            f"/todos/upcoming/?to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        titles = [t["title"] for t in response.json()]
        assert "Scenario3c Future Todo" not in titles


class TestExtremeTimeValues:
    def test_far_future_time_no_error(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        far_future = (utc_now + timedelta(days=365 * 100)).replace(tzinfo=timezone.utc)
        
        response = client.post("/todos/", json={
            "title": "Far Future Todo",
            "status": "not_done",
            "reminder_time": far_future.isoformat()
        }, headers=auth_headers)
        
        assert response.status_code == 200
        
        from_time = (utc_now + timedelta(days=365 * 50)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(days=365 * 200)).replace(tzinfo=timezone.utc)
        
        query_response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert query_response.status_code == 200
        titles = [t["title"] for t in query_response.json()]
        assert "Far Future Todo" in titles
    
    def test_past_time_no_error(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        past_time = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        response = client.post("/todos/", json={
            "title": "Past Time Todo",
            "status": "not_done",
            "reminder_time": past_time.isoformat()
        }, headers=auth_headers)
        
        assert response.status_code == 200
        
        from_time = datetime(1990, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        to_time = datetime(2010, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        query_response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert query_response.status_code == 200
        titles = [t["title"] for t in query_response.json()]
        assert "Past Time Todo" in titles
    
    def test_microsecond_precision_preserved(self):
        time_with_micro = datetime(2026, 5, 1, 10, 0, 0, 123456, tzinfo=timezone.utc)
        
        result = normalize_to_utc_naive(time_with_micro)
        
        assert result.microsecond == 123456
    
    def test_microsecond_comparison_precise(self):
        from_time = datetime(2026, 5, 1, 10, 0, 0, 500000)
        to_time = datetime(2026, 5, 1, 10, 0, 0, 499999)
        
        with pytest.raises(ValueError, match="Invalid time range"):
            validate_time_range(from_time, to_time)


class TestErrorMessageConsistency:
    def test_error_message_contains_time_values(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=5)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        detail = response.json()["detail"]
        
        assert "Z)" in detail
        assert "Invalid time range" in detail
        assert "cannot be earlier than" in detail
    
    def test_error_message_contains_helpful_hint(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_time = (utc_now + timedelta(hours=5)).replace(tzinfo=timezone.utc)
        to_time = (utc_now + timedelta(hours=3)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_time)}&to_time={format_time_for_url(to_time)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        detail = response.json()["detail"]
        
        assert "Both parameters are explicitly provided" in detail
        assert "use only 'to_time' parameter" in detail
    
    def test_error_message_with_timezone_conversion(self, auth_headers):
        utc_now = datetime.now(timezone.utc)
        from_beijing = (utc_now + timedelta(hours=13)).replace(tzinfo=timezone(timedelta(hours=8)))
        to_utc = (utc_now + timedelta(hours=4)).replace(tzinfo=timezone.utc)
        
        response = client.get(
            f"/todos/upcoming/?from_time={format_time_for_url(from_beijing)}&to_time={format_time_for_url(to_utc)}",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        detail = response.json()["detail"]
        
        from_utc_naive = from_beijing.astimezone(timezone.utc).replace(tzinfo=None)
        assert from_utc_naive.isoformat() in detail