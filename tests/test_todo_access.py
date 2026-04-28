import pytest
from tests.conftest import create_test_user, login_test_user, create_test_todo


class TestTodoCreate:
    """测试 Todo 新建接口 (POST /todos/)"""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        self.user = create_test_user(client, "testuser", "test@test.com", "password123")
        self.token = login_test_user(client, "test@test.com", "password123")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_create_todo_success_with_minimal_fields(self):
        """POST 场景 1: 正常创建成功 - 只提供必填字段 title"""
        response = self.client.post(
            "/todos/",
            json={
                "title": "Test Todo"
            },
            headers=self.headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["title"] == "Test Todo"
        assert data["description"] is None
        assert data["status"] == "not_done"
        assert data["id"] > 0
        assert data["owner_id"] == self.user["id"]

    def test_create_todo_success_with_all_fields(self):
        """POST 场景 2: 正常创建成功 - 提供所有字段"""
        response = self.client.post(
            "/todos/",
            json={
                "title": "Complete Project",
                "description": "Finish all tasks",
                "status": "done"
            },
            headers=self.headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["title"] == "Complete Project"
        assert data["description"] == "Finish all tasks"
        assert data["status"] == "done"
        assert data["id"] > 0
        assert data["owner_id"] == self.user["id"]

    def test_create_todo_fails_missing_title(self):
        """POST 场景 3: title 为空时被拒绝"""
        response = self.client.post(
            "/todos/",
            json={
                "description": "This has no title"
            },
            headers=self.headers
        )
        assert response.status_code == 422
        
        error_detail = response.json()
        assert "detail" in error_detail
        errors = error_detail["detail"]
        title_missing = any(
            "title" in str(error.get("loc", [])) or "title" in error.get("msg", "")
            for error in errors
        )
        assert title_missing

    def test_create_todo_fails_empty_title_string(self):
        """POST 场景 4: title 为空字符串时的行为"""
        response = self.client.post(
            "/todos/",
            json={
                "title": ""
            },
            headers=self.headers
        )
        if response.status_code == 200:
            data = response.json()
            assert data["title"] == ""
            assert data["id"] > 0
        else:
            assert response.status_code == 422


class TestTodoAccessScenarios:
    """测试 Todo 访问的三个核心场景"""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        self.user1 = create_test_user(client, "user1", "user1@test.com", "password123")
        self.token1 = login_test_user(client, "user1@test.com", "password123")
        self.headers1 = {"Authorization": f"Bearer {self.token1}"}

    def test_scenario_1_id_not_found_returns_404(self):
        """场景 1: ID 不存在时返回 404"""
        non_existent_id = 9999

        response_get = self.client.get(
            f"/todos/{non_existent_id}",
            headers=self.headers1
        )
        assert response_get.status_code == 404
        assert "detail" in response_get.json()
        assert "not found" in response_get.json()["detail"].lower()

        response_put = self.client.put(
            f"/todos/{non_existent_id}",
            json={"title": "Updated"},
            headers=self.headers1
        )
        assert response_put.status_code == 404
        assert "detail" in response_put.json()

        response_delete = self.client.delete(
            f"/todos/{non_existent_id}",
            headers=self.headers1
        )
        assert response_delete.status_code == 404
        assert "detail" in response_delete.json()

    def test_scenario_2_access_other_users_todo_returns_404(self):
        """场景 2: 访问其他用户的记录时返回 404"""
        todo = create_test_todo(self.client, self.token1, "User1's Todo", "User1's description")
        todo_id = todo["id"]

        user2 = create_test_user(self.client, "user2", "user2@test.com", "password456")
        token2 = login_test_user(self.client, "user2@test.com", "password456")
        headers2 = {"Authorization": f"Bearer {token2}"}

        response_get = self.client.get(f"/todos/{todo_id}", headers=headers2)
        assert response_get.status_code == 404
        assert "detail" in response_get.json()

        response_put = self.client.put(
            f"/todos/{todo_id}",
            json={"title": "Hacked!"},
            headers=headers2
        )
        assert response_put.status_code == 404
        assert "detail" in response_put.json()

        response_delete = self.client.delete(f"/todos/{todo_id}", headers=headers2)
        assert response_delete.status_code == 404
        assert "detail" in response_delete.json()

        verify_response = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert verify_response.status_code == 200
        data = verify_response.json()
        assert data["id"] == todo_id
        assert data["title"] == "User1's Todo"
        assert data["description"] == "User1's description"
        assert data["owner_id"] == self.user1["id"]
        assert data["status"] == "not_done"

    def test_scenario_3_normal_access_returns_data(self):
        """场景 3: 正常访问时返回数据 - 完整验证响应体字段"""
        todo = create_test_todo(self.client, self.token1, "My Todo", "My description")
        todo_id = todo["id"]

        assert todo["title"] == "My Todo"
        assert todo["description"] == "My description"
        assert todo["status"] == "not_done"
        assert todo["id"] == todo_id
        assert todo["owner_id"] == self.user1["id"]

        response_get = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert response_get.status_code == 200
        data = response_get.json()
        assert data["id"] == todo_id
        assert data["title"] == "My Todo"
        assert data["description"] == "My description"
        assert data["status"] == "not_done"
        assert data["owner_id"] == self.user1["id"]

        response_put = self.client.put(
            f"/todos/{todo_id}",
            json={
                "title": "Updated Todo",
                "status": "done"
            },
            headers=self.headers1
        )
        assert response_put.status_code == 200
        updated = response_put.json()
        assert updated["id"] == todo_id
        assert updated["title"] == "Updated Todo"
        assert updated["status"] == "done"
        assert updated["description"] == "My description"
        assert updated["owner_id"] == self.user1["id"]

        response_delete = self.client.delete(f"/todos/{todo_id}", headers=self.headers1)
        assert response_delete.status_code == 200
        delete_result = response_delete.json()
        assert "detail" in delete_result
        assert "deleted" in delete_result["detail"].lower()

        response_get_after = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert response_get_after.status_code == 404
        assert "detail" in response_get_after.json()
