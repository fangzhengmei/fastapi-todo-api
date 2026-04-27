import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base
from app.dependencies import get_db
from app import models, auth

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


@pytest.fixture(scope="function")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_user1(client):
    response = client.post(
        "/register",
        json={
            "username": "testuser1",
            "email": "test1@example.com",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="function")
def test_user2(client):
    response = client.post(
        "/register",
        json={
            "username": "testuser2",
            "email": "test2@example.com",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="function")
def test_user3(client):
    response = client.post(
        "/register",
        json={
            "username": "testuser3",
            "email": "test3@example.com",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 200
    return response.json()


def get_auth_token(client, email, password):
    response = client.post(
        "/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def create_todo(client, token, title, description=None):
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/todos/",
        json={"title": title, "description": description},
        headers=headers
    )
    assert response.status_code == 200
    return response.json()


class TestUserSharing:
    
    def test_share_todo_to_user(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared Todo", "This is a shared todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_only"
            },
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["permission"] == "read_only"
        assert data["shared_with"]["username"] == "testuser2"
        assert data["shared_by"]["username"] == "testuser1"
    
    def test_share_todo_to_user_with_read_write_permission(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Editable Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_write"
            },
            headers=headers
        )
        
        assert response.status_code == 200
        assert response.json()["permission"] == "read_write"
    
    def test_cannot_share_to_nonexistent_user(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "nonexistent",
                "permission": "read_only"
            },
            headers=headers
        )
        
        assert response.status_code == 404
    
    def test_cannot_share_to_self(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser1",
                "permission": "read_only"
            },
            headers=headers
        )
        
        assert response.status_code == 400
    
    def test_cannot_share_nonexistent_todo(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            "/todos/9999/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_only"
            },
            headers=headers
        )
        
        assert response.status_code == 404
    
    def test_shared_user_can_view_todo(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_only"
            },
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.get(f"/todos/{todo['id']}", headers=headers2)
        
        assert response.status_code == 200
        assert response.json()["title"] == "Shared Todo"
    
    def test_shared_user_with_read_only_cannot_update(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_only"
            },
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Updated Title"},
            headers=headers2
        )
        
        assert response.status_code == 403
    
    def test_shared_user_with_read_write_can_update(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "read_write"
            },
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Updated Title", "status": "done"},
            headers=headers2
        )
        
        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"
        assert response.json()["status"] == "done"
    
    def test_get_received_shares(self, client, test_user1, test_user2, test_user3):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        
        todo1 = create_todo(client, token1, "Todo 1")
        todo2 = create_todo(client, token1, "Todo 2")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo1['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_only"},
            headers=headers1
        )
        client.post(
            f"/todos/{todo2['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_write"},
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.get("/shares/received", headers=headers2)
        
        assert response.status_code == 200
        assert len(response.json()) == 2
    
    def test_get_given_shares(self, client, test_user1, test_user2, test_user3):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        
        todo1 = create_todo(client, token1, "Todo 1")
        todo2 = create_todo(client, token1, "Todo 2")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo1['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_only"},
            headers=headers1
        )
        client.post(
            f"/todos/{todo2['id']}/share",
            json={"shared_with_username": "testuser3", "permission": "read_write"},
            headers=headers1
        )
        
        response = client.get("/shares/given", headers=headers1)
        
        assert response.status_code == 200
        assert len(response.json()) == 2
    
    def test_revoke_share(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        share_response = client.post(
            f"/todos/{todo['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_only"},
            headers=headers1
        )
        share_id = share_response.json()["id"]
        
        client.delete(f"/shares/{share_id}", headers=headers1)
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.get(f"/todos/{todo['id']}", headers=headers2)
        
        assert response.status_code == 404
    
    def test_get_todos_with_include_shared(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        
        create_todo(client, token2, "User2's Own Todo")
        todo = create_todo(client, token1, "Shared Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_only"},
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        response = client.get("/todos/?include_shared=true", headers=headers2)
        
        assert response.status_code == 200
        todos = response.json()
        assert len(todos) == 2
        titles = [t["title"] for t in todos]
        assert "User2's Own Todo" in titles
        assert "Shared Todo" in titles


class TestShareLinks:
    
    def test_create_share_link(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Link Shared Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["permission"] == "read_only"
        assert data["share_token"] is not None
        assert data["share_url"] is not None
        assert data["is_password_protected"] is False
    
    def test_create_password_protected_share_link(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_only",
                "is_password_protected": True,
                "password": "linkpass123"
            },
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_password_protected"] is True
    
    def test_get_share_link_info(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Link Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        info_response = client.get(f"/share-links/{share_token}/info")
        
        assert info_response.status_code == 200
        data = info_response.json()
        assert data["todo_title"] == "Link Todo"
        assert data["shared_by"] == "testuser1"
    
    def test_access_share_link(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Link Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        access_response = client.post(
            f"/share-links/{share_token}/access",
            json={}
        )
        
        assert access_response.status_code == 200
        data = access_response.json()
        assert data["todo"]["title"] == "Link Todo"
        assert data["permission"] == "read_only"
        assert data["share_type"] == "link"
    
    def test_access_password_protected_link_with_correct_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_write",
                "is_password_protected": True,
                "password": "mypass123"
            },
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        access_response = client.post(
            f"/share-links/{share_token}/access",
            json={"password": "mypass123"}
        )
        
        assert access_response.status_code == 200
        assert access_response.json()["todo"]["title"] == "Protected Todo"
    
    def test_access_password_protected_link_with_wrong_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_write",
                "is_password_protected": True,
                "password": "mypass123"
            },
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        access_response = client.post(
            f"/share-links/{share_token}/access",
            json={"password": "wrongpass"}
        )
        
        assert access_response.status_code == 401
    
    def test_access_password_protected_link_without_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_write",
                "is_password_protected": True,
                "password": "mypass123"
            },
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        access_response = client.post(
            f"/share-links/{share_token}/access",
            json={}
        )
        
        assert access_response.status_code == 401
    
    def test_deactivate_share_link(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        link_id = link_response.json()["id"]
        share_token = link_response.json()["share_token"]
        
        deactivate_response = client.put(
            f"/share-links/{link_id}/deactivate",
            headers=headers
        )
        
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False
        
        access_response = client.post(
            f"/share-links/{share_token}/access",
            json={}
        )
        
        assert access_response.status_code == 410
    
    def test_delete_share_link(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        link_id = link_response.json()["id"]
        
        delete_response = client.delete(
            f"/share-links/{link_id}",
            headers=headers
        )
        
        assert delete_response.status_code == 200
        
        links_response = client.get(
            f"/todos/{todo['id']}/share-links",
            headers=headers
        )
        
        assert len(links_response.json()) == 0
    
    def test_get_todo_share_links(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_write",
                "is_password_protected": True,
                "password": "pass123"
            },
            headers=headers
        )
        
        links_response = client.get(
            f"/todos/{todo['id']}/share-links",
            headers=headers
        )
        
        assert links_response.status_code == 200
        assert len(links_response.json()) == 2
    
    def test_views_counter_increments(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers
        )
        share_token = link_response.json()["share_token"]
        
        assert link_response.json()["views"] == 0
        
        for _ in range(3):
            client.post(f"/share-links/{share_token}/access", json={})
        
        info_response = client.get(
            f"/todos/{todo['id']}/share-links",
            headers=headers
        )
        
        links = info_response.json()
        assert len(links) == 1
        assert links[0]["views"] == 3


class TestInvalidPermissions:
    
    def test_invalid_permission_value(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers = {"Authorization": f"Bearer {token1}"}
        response = client.post(
            f"/todos/{todo['id']}/share",
            json={
                "shared_with_username": "testuser2",
                "permission": "invalid_permission"
            },
            headers=headers
        )
        
        assert response.status_code == 400


class TestEdgeCases:
    
    def test_update_existing_share_changes_permission(self, client, test_user1, test_user2):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        token2 = get_auth_token(client, "test2@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        client.post(
            f"/todos/{todo['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_only"},
            headers=headers1
        )
        
        headers2 = {"Authorization": f"Bearer {token2}"}
        update_response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Should Fail"},
            headers=headers2
        )
        assert update_response.status_code == 403
        
        client.post(
            f"/todos/{todo['id']}/share",
            json={"shared_with_username": "testuser2", "permission": "read_write"},
            headers=headers1
        )
        
        update_response2 = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Should Succeed"},
            headers=headers2
        )
        assert update_response2.status_code == 200
        assert update_response2.json()["title"] == "Should Succeed"
    
    def test_nonexistent_share_link(self, client):
        response = client.get("/share-links/non-existent-token/info")
        assert response.status_code == 404
    
    def test_nonexistent_share(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        headers = {"Authorization": f"Bearer {token1}"}
        
        response = client.delete("/shares/9999", headers=headers)
        assert response.status_code == 404


class TestShareLinkTokenAuthorization:
    
    def test_read_todo_using_share_link_token(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Shared via Link")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        link_headers = {"X-Share-Token": share_token}
        get_response = client.get(f"/todos/{todo['id']}", headers=link_headers)
        
        assert get_response.status_code == 200
        assert get_response.json()["title"] == "Shared via Link"
    
    def test_update_todo_using_read_write_share_link_token(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Editable via Link")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_write"},
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        link_headers = {"X-Share-Token": share_token}
        update_response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Updated via Link", "status": "done"},
            headers=link_headers
        )
        
        assert update_response.status_code == 200
        assert update_response.json()["title"] == "Updated via Link"
        assert update_response.json()["status"] == "done"
    
    def test_read_only_share_link_token_cannot_update(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Read Only Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        link_headers = {"X-Share-Token": share_token}
        update_response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Should Not Update"},
            headers=link_headers
        )
        
        assert update_response.status_code == 403
    
    def test_invalid_share_link_token_rejected(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        invalid_headers = {"X-Share-Token": "invalid-token-123"}
        get_response = client.get(f"/todos/{todo['id']}", headers=invalid_headers)
        
        assert get_response.status_code == 404
    
    def test_deactivated_share_link_token_rejected(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers1
        )
        link_id = link_response.json()["id"]
        share_token = link_response.json()["share_token"]
        
        client.put(f"/share-links/{link_id}/deactivate", headers=headers1)
        
        link_headers = {"X-Share-Token": share_token}
        get_response = client.get(f"/todos/{todo['id']}", headers=link_headers)
        
        assert get_response.status_code == 404
    
    def test_share_link_token_for_wrong_todo_rejected(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo1 = create_todo(client, token1, "Todo 1")
        todo2 = create_todo(client, token1, "Todo 2")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo1['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        link_headers = {"X-Share-Token": share_token}
        get_response = client.get(f"/todos/{todo2['id']}", headers=link_headers)
        
        assert get_response.status_code == 404
    
    def test_password_protected_share_link_with_correct_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_only",
                "is_password_protected": True,
                "password": "secret123"
            },
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        link_headers = {"X-Share-Token": share_token, "X-Share-Password": "secret123"}
        get_response = client.get(f"/todos/{todo['id']}", headers=link_headers)
        
        assert get_response.status_code == 200
        assert get_response.json()["title"] == "Protected Todo"
    
    def test_password_protected_share_link_with_wrong_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_only",
                "is_password_protected": True,
                "password": "secret123"
            },
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        wrong_headers = {"X-Share-Token": share_token, "X-Share-Password": "wrongpass"}
        get_response = client.get(f"/todos/{todo['id']}", headers=wrong_headers)
        
        assert get_response.status_code == 404
    
    def test_password_protected_share_link_without_password(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Protected Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={
                "permission": "read_write",
                "is_password_protected": True,
                "password": "secret123"
            },
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        no_password_headers = {"X-Share-Token": share_token}
        get_response = client.get(f"/todos/{todo['id']}", headers=no_password_headers)
        
        assert get_response.status_code == 404
    
    def test_no_authentication_returns_401(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        get_response = client.get(f"/todos/{todo['id']}")
        
        assert get_response.status_code == 401
    
    def test_bearer_token_and_share_token_both_work(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Test Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_write"},
            headers=headers1
        )
        share_token = link_response.json()["share_token"]
        
        bearer_response = client.get(f"/todos/{todo['id']}", headers=headers1)
        assert bearer_response.status_code == 200
        
        link_headers = {"X-Share-Token": share_token}
        link_response = client.get(f"/todos/{todo['id']}", headers=link_headers)
        assert link_response.status_code == 200
        
        assert bearer_response.json()["id"] == link_response.json()["id"]
    
    def test_expired_share_link_token_rejected_on_read(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Expired Link Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_only"},
            headers=headers1
        )
        link_id = link_response.json()["id"]
        share_token = link_response.json()["share_token"]
        
        db = TestingSessionLocal()
        try:
            link = db.query(models.TodoShareLink).filter_by(id=link_id).first()
            link.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        finally:
            db.close()
        
        link_headers = {"X-Share-Token": share_token}
        get_response = client.get(f"/todos/{todo['id']}", headers=link_headers)
        
        assert get_response.status_code == 404
    
    def test_expired_share_link_token_rejected_on_write(self, client, test_user1):
        token1 = get_auth_token(client, "test1@example.com", "testpassword123")
        todo = create_todo(client, token1, "Expired Write Link Todo")
        
        headers1 = {"Authorization": f"Bearer {token1}"}
        link_response = client.post(
            f"/todos/{todo['id']}/share-link",
            json={"permission": "read_write"},
            headers=headers1
        )
        link_id = link_response.json()["id"]
        share_token = link_response.json()["share_token"]
        
        db = TestingSessionLocal()
        try:
            link = db.query(models.TodoShareLink).filter_by(id=link_id).first()
            link.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        finally:
            db.close()
        
        link_headers = {"X-Share-Token": share_token}
        update_response = client.put(
            f"/todos/{todo['id']}",
            json={"title": "Should Not Update"},
            headers=link_headers
        )
        
        assert update_response.status_code == 404
