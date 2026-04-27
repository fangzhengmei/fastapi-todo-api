import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base
from app.dependencies import get_db
from app.config import settings

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
    "username": "testuser",
    "email": "testuser@example.com",
    "password": "testpassword123"
}

@pytest.fixture(scope="module")
def test_user_token():
    Base.metadata.create_all(bind=engine)
    
    response = client.post("/register", json=TEST_USER)
    assert response.status_code == 200
    
    login_response = client.post("/login", json={
        "email": TEST_USER["email"],
        "password": TEST_USER["password"]
    })
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    yield token
    
    Base.metadata.drop_all(bind=engine)

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

def test_create_todo(create_test_todo):
    """Test creating a todo item"""
    todo = create_test_todo(title="Test Todo 1", description="This is a test todo")
    assert todo["title"] == "Test Todo 1"
    assert todo["is_deleted"] == False
    assert todo["deleted_at"] is None

def test_get_todos_before_delete(auth_headers, create_test_todo):
    """Test getting todos before any are deleted"""
    create_test_todo(title="Test Todo 2", description="Another test todo")
    
    response = client.get("/todos/", headers=auth_headers)
    assert response.status_code == 200
    todos = response.json()
    assert len(todos) >= 1
    for todo in todos:
        assert todo["is_deleted"] == False

def test_soft_delete_todo(auth_headers, create_test_todo):
    """Test soft deleting a todo (moving to trash)"""
    todo = create_test_todo(title="Todo to Delete", description="This will be deleted")
    todo_id = todo["id"]
    
    delete_response = client.delete(f"/todos/{todo_id}", headers=auth_headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["detail"] == "Todo moved to trash"
    
    get_response = client.get("/todos/", headers=auth_headers)
    assert get_response.status_code == 200
    todos = get_response.json()
    todo_ids = [t["id"] for t in todos]
    assert todo_id not in todo_ids
    
    get_single_response = client.get(f"/todos/{todo_id}", headers=auth_headers)
    assert get_single_response.status_code == 404

def test_get_trash_list(auth_headers, create_test_todo):
    """Test getting the list of deleted todos (trash)"""
    todo = create_test_todo(title="Trash Todo 1", description="For trash list test")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    response = client.get("/todos/trash/", headers=auth_headers)
    assert response.status_code == 200
    trash_items = response.json()
    
    assert len(trash_items) >= 1
    trash_ids = [t["id"] for t in trash_items]
    assert todo_id in trash_ids
    
    deleted_todo = next(t for t in trash_items if t["id"] == todo_id)
    assert deleted_todo["is_deleted"] == True
    assert deleted_todo["deleted_at"] is not None

def test_get_single_trash_item(auth_headers, create_test_todo):
    """Test getting a single deleted todo from trash"""
    todo = create_test_todo(title="Single Trash Todo", description="For single trash test")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    response = client.get(f"/todos/trash/{todo_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    assert data["id"] == todo_id
    assert data["is_deleted"] == True
    assert data["deleted_at"] is not None

def test_get_nonexistent_trash_item(auth_headers):
    """Test getting a nonexistent todo from trash"""
    response = client.get("/todos/trash/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found in trash"

def test_restore_todo(auth_headers, create_test_todo):
    """Test restoring a todo from trash"""
    todo = create_test_todo(title="Todo to Restore", description="This will be restored")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    restore_response = client.post(f"/todos/{todo_id}/restore", headers=auth_headers)
    assert restore_response.status_code == 200
    restored_todo = restore_response.json()
    
    assert restored_todo["is_deleted"] == False
    assert restored_todo["deleted_at"] is None
    
    get_response = client.get("/todos/", headers=auth_headers)
    assert get_response.status_code == 200
    todos = get_response.json()
    todo_ids = [t["id"] for t in todos]
    assert todo_id in todo_ids
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id not in trash_ids

def test_restore_nonexistent_todo(auth_headers):
    """Test restoring a nonexistent todo"""
    response = client.post("/todos/999999/restore", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found in trash"

def test_restore_already_active_todo(auth_headers, create_test_todo):
    """Test restoring a todo that's not in trash"""
    todo = create_test_todo(title="Active Todo", description="Not in trash")
    todo_id = todo["id"]
    
    restore_response = client.post(f"/todos/{todo_id}/restore", headers=auth_headers)
    assert restore_response.status_code == 404
    assert restore_response.json()["detail"] == "Todo not found in trash"

def test_permanent_delete_todo(auth_headers, create_test_todo):
    """Test permanently deleting a todo from trash"""
    todo = create_test_todo(title="Todo to Permanent Delete", description="This will be gone forever")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    perm_delete_response = client.delete(f"/todos/{todo_id}/permanent", headers=auth_headers)
    assert perm_delete_response.status_code == 200
    assert perm_delete_response.json()["detail"] == "Todo permanently deleted"
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_ids = [t["id"] for t in trash_response.json()]
    assert todo_id not in trash_ids
    
    get_trash_response = client.get(f"/todos/trash/{todo_id}", headers=auth_headers)
    assert get_trash_response.status_code == 404

def test_permanent_delete_nonexistent_todo(auth_headers):
    """Test permanently deleting a nonexistent todo"""
    response = client.delete("/todos/999999/permanent", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Todo not found in trash"

def test_permanent_delete_active_todo(auth_headers, create_test_todo):
    """Test permanently deleting a todo that's not in trash"""
    todo = create_test_todo(title="Another Active Todo", description="Still active")
    todo_id = todo["id"]
    
    perm_delete_response = client.delete(f"/todos/{todo_id}/permanent", headers=auth_headers)
    assert perm_delete_response.status_code == 404
    assert perm_delete_response.json()["detail"] == "Todo not found in trash"

def test_empty_trash(auth_headers, create_test_todo):
    """Test emptying the entire trash"""
    todos_to_create = [
        {"title": "Trash Item 1", "description": "To be emptied"},
        {"title": "Trash Item 2", "description": "To be emptied"},
        {"title": "Trash Item 3", "description": "To be emptied"},
    ]
    
    created_ids = []
    for todo_data in todos_to_create:
        todo = create_test_todo(**todo_data)
        created_ids.append(todo["id"])
    
    for todo_id in created_ids:
        client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    trash_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_response.status_code == 200
    trash_items = trash_response.json()
    trash_ids = [t["id"] for t in trash_items]
    for todo_id in created_ids:
        assert todo_id in trash_ids
    
    empty_response = client.delete("/todos/trash/empty", headers=auth_headers)
    assert empty_response.status_code == 200
    empty_detail = empty_response.json()["detail"]
    assert "Emptied" in empty_detail
    assert "items from trash" in empty_detail
    
    trash_after_response = client.get("/todos/trash/", headers=auth_headers)
    assert trash_after_response.status_code == 200
    trash_after_ids = [t["id"] for t in trash_after_response.json()]
    for todo_id in created_ids:
        assert todo_id not in trash_after_ids

def test_update_deleted_todo_not_allowed(auth_headers, create_test_todo):
    """Test that deleted todos cannot be updated"""
    todo = create_test_todo(title="Todo to Update Test", description="Original description")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    update_response = client.put(
        f"/todos/{todo_id}",
        json={"title": "Updated Title", "description": "Updated description"},
        headers=auth_headers
    )
    assert update_response.status_code == 404
    assert update_response.json()["detail"] == "Todo not found"

def test_delete_already_deleted_todo(auth_headers, create_test_todo):
    """Test that deleting an already deleted todo fails"""
    todo = create_test_todo(title="Already Deleted Todo", description="Test")
    todo_id = todo["id"]
    
    client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    delete_response2 = client.delete(f"/todos/{todo_id}", headers=auth_headers)
    assert delete_response2.status_code == 404
    assert delete_response2.json()["detail"] == "Todo not found"

def test_trash_sorting(auth_headers, create_test_todo):
    """Test that trash items can be sorted"""
    todos = [
        {"title": "Zebra Todo", "description": "Z"},
        {"title": "Apple Todo", "description": "A"},
        {"title": "Mango Todo", "description": "M"},
    ]
    
    created_ids = []
    for todo_data in todos:
        todo = create_test_todo(**todo_data)
        created_ids.append(todo["id"])
    
    for todo_id in created_ids:
        client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    response = client.get("/todos/trash/?sort=title", headers=auth_headers)
    assert response.status_code == 200
    trash_items = response.json()
    
    test_titles = ["Apple Todo", "Mango Todo", "Zebra Todo"]
    our_items = [t for t in trash_items if t["title"] in test_titles]
    
    titles = [t["title"] for t in our_items]
    assert titles == sorted(titles, reverse=True)

def test_trash_pagination(auth_headers, create_test_todo):
    """Test pagination for trash list"""
    created_ids = []
    for i in range(15):
        todo = create_test_todo(
            title=f"Paginated Todo {i}", 
            description=f"Test pagination {i}"
        )
        created_ids.append(todo["id"])
    
    for todo_id in created_ids:
        client.delete(f"/todos/{todo_id}", headers=auth_headers)
    
    response1 = client.get("/todos/trash/?limit=5&offset=0", headers=auth_headers)
    assert response1.status_code == 200
    page1 = response1.json()
    assert len(page1) == 5
    
    response2 = client.get("/todos/trash/?limit=5&offset=5", headers=auth_headers)
    assert response2.status_code == 200
    page2 = response2.json()
    assert len(page2) == 5
    
    page1_ids = {t["id"] for t in page1}
    page2_ids = {t["id"] for t in page2}
    assert page1_ids.isdisjoint(page2_ids)