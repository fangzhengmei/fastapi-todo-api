import pytest
from tests.conftest import create_test_user, login_test_user, create_test_todo


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
        assert "not found" in response_get.json()["detail"].lower()

        response_put = self.client.put(
            f"/todos/{non_existent_id}",
            json={"title": "Updated"},
            headers=self.headers1
        )
        assert response_put.status_code == 404

        response_delete = self.client.delete(
            f"/todos/{non_existent_id}",
            headers=self.headers1
        )
        assert response_delete.status_code == 404

    def test_scenario_2_access_other_users_todo_returns_404(self):
        """场景 2: 访问其他用户的记录时返回 404"""
        todo = create_test_todo(self.client, self.token1, "User1's Todo")
        todo_id = todo["id"]

        user2 = create_test_user(self.client, "user2", "user2@test.com", "password456")
        token2 = login_test_user(self.client, "user2@test.com", "password456")
        headers2 = {"Authorization": f"Bearer {token2}"}

        response_get = self.client.get(f"/todos/{todo_id}", headers=headers2)
        assert response_get.status_code == 404

        response_put = self.client.put(
            f"/todos/{todo_id}",
            json={"title": "Hacked!"},
            headers=headers2
        )
        assert response_put.status_code == 404

        response_delete = self.client.delete(f"/todos/{todo_id}", headers=headers2)
        assert response_delete.status_code == 404

        verify_response = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert verify_response.status_code == 200
        assert verify_response.json()["title"] == "User1's Todo"

    def test_scenario_3_normal_access_returns_data(self):
        """场景 3: 正常访问时返回数据"""
        todo = create_test_todo(self.client, self.token1, "My Todo", "My description")
        todo_id = todo["id"]

        response_get = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert response_get.status_code == 200
        data = response_get.json()
        assert data["id"] == todo_id
        assert data["title"] == "My Todo"
        assert data["description"] == "My description"
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
        assert updated["title"] == "Updated Todo"
        assert updated["status"] == "done"
        assert updated["description"] == "My description"

        response_delete = self.client.delete(f"/todos/{todo_id}", headers=self.headers1)
        assert response_delete.status_code == 200
        assert "deleted" in response_delete.json()["detail"].lower()

        response_get_after = self.client.get(f"/todos/{todo_id}", headers=self.headers1)
        assert response_get_after.status_code == 404
