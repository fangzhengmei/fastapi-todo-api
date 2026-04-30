import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import io
import csv

from app.main import app
from app.database import Base
from app.dependencies import get_db
from app import models, auth

# 创建测试数据库
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 覆盖数据库依赖
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# 创建测试客户端
client = TestClient(app)

# 创建测试用户
TEST_USER_USERNAME = "testuser"
TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "testpassword123"


@pytest.fixture(scope="function")
def test_db():
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    yield
    # 删除所有表
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def auth_headers(test_db):
    # 注册用户
    response = client.post(
        "/register",
        json={
            "username": TEST_USER_USERNAME,
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        }
    )
    assert response.status_code == 200
    
    # 登录获取 token
    response = client.post(
        "/login",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        }
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    
    return {"Authorization": f"Bearer {token}"}


class TestCSVImport:
    """Test CSV import functionality"""
    
    def test_import_valid_csv(self, auth_headers):
        """Test importing a valid CSV file with multiple todos"""
        # 创建 CSV 内容（注意：包含逗号的字段需要用引号包裹）
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done
Finish report,"Complete the quarterly report",done
Call client,"Discuss project details",not_done"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0
        assert len(data["successful_items"]) == 3
        assert len(data["failed_items"]) == 0
        
        # 验证 todos 确实被创建
        response = client.get("/todos/", headers=auth_headers)
        assert response.status_code == 200
        todos = response.json()
        assert len(todos) == 3
        
        # 验证 todo 数据
        titles = [todo["title"] for todo in todos]
        assert "Buy groceries" in titles
        assert "Finish report" in titles
        assert "Call client" in titles
    
    def test_import_csv_without_status(self, auth_headers):
        """Test importing CSV without status column (should use default)"""
        # 创建 CSV 内容（没有 status 列，包含逗号的字段用引号包裹）
        csv_content = """title,description
Buy groceries,"Milk, Bread, Eggs"
Finish report,"Complete the quarterly report"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 2
        assert data["successful"] == 2
        
        # 验证 todos 状态为默认值
        response = client.get("/todos/", headers=auth_headers)
        todos = response.json()
        for todo in todos:
            assert todo["status"] == "not_done"
    
    def test_import_csv_with_invalid_rows(self, auth_headers):
        """Test importing CSV with some invalid rows"""
        # 创建 CSV 内容（包含无效行，包含逗号的字段用引号包裹）
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done
,"Empty title",not_done
Finish report,"Complete the quarterly report",invalid_status
Call client,"Discuss project details",done"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 4
        assert data["successful"] == 2
        assert data["failed"] == 2
        
        # 验证失败的行
        failed_items = data["failed_items"]
        assert len(failed_items) == 2
        
        # 检查第一个失败的行（空标题）
        assert "Title is required" in failed_items[0]["errors"][0]
        
        # 检查第二个失败的行（无效状态）
        assert "Status must be one of" in failed_items[1]["errors"][0]
        
        # 验证只有 2 个 todos 被创建
        response = client.get("/todos/", headers=auth_headers)
        todos = response.json()
        assert len(todos) == 2
    
    def test_import_csv_without_title_column(self, auth_headers):
        """Test importing CSV without title column (should fail)"""
        # 创建 CSV 内容（没有 title 列）
        csv_content = """description,status
Milk, Bread, Eggs,not_done
Complete the quarterly report,done"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应（应该失败）
        assert response.status_code == 400
        assert "title" in response.json()["detail"]
    
    def test_import_non_csv_file(self, auth_headers):
        """Test importing a non-CSV file (should fail)"""
        # 创建非 CSV 内容
        content = "This is not a CSV file"
        
        # 上传文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.txt", content, "text/plain")},
            headers=auth_headers
        )
        
        # 检查响应（应该失败）
        assert response.status_code == 400
        assert "CSV" in response.json()["detail"]
    
    def test_import_empty_csv(self, auth_headers):
        """Test importing an empty CSV file"""
        # 创建空 CSV 内容（只有标题行）
        csv_content = """title,description,status"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 0
        assert data["successful"] == 0
        assert data["failed"] == 0
    
    def test_import_without_auth(self):
        """Test importing CSV without authentication (should fail)"""
        # 创建 CSV 内容
        csv_content = """title,description,status
Buy groceries,Milk, Bread, Eggs,not_done"""
        
        # 上传 CSV 文件（没有认证头）
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        
        # 检查响应（应该失败）
        assert response.status_code == 401
    
    def test_import_dry_run_valid_csv(self, auth_headers):
        """Test dry_run mode with valid CSV - should not save to database"""
        # 创建 CSV 内容
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done
Finish report,"Complete the quarterly report",done"""
        
        # 上传 CSV 文件，使用 dry_run=True
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"dry_run": "true"},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 2
        assert data["successful"] == 2
        assert data["failed"] == 0
        
        # 验证 successful_items 中的 id 是 None（dry run 模式）
        for item in data["successful_items"]:
            assert item["id"] is None
        
        # 验证 todos 没有被保存到数据库
        response = client.get("/todos/", headers=auth_headers)
        assert response.status_code == 200
        todos = response.json()
        assert len(todos) == 0  # 应该是空的，因为是 dry run
    
    def test_import_dry_run_with_invalid_rows(self, auth_headers):
        """Test dry_run mode with invalid rows - should return same structure as normal import"""
        # 创建 CSV 内容（包含无效行）
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done
,"Empty title",not_done
Finish report,"Complete the quarterly report",done"""
        
        # 上传 CSV 文件，使用 dry_run=True
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"dry_run": "true"},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1
        
        # 验证失败的行
        failed_items = data["failed_items"]
        assert len(failed_items) == 1
        assert "Title is required" in failed_items[0]["errors"][0]
        
        # 验证 todos 没有被保存到数据库
        response = client.get("/todos/", headers=auth_headers)
        todos = response.json()
        assert len(todos) == 0
    
    def test_import_dry_run_default_false(self, auth_headers):
        """Test that dry_run defaults to false (normal import)"""
        # 创建 CSV 内容
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done"""
        
        # 上传 CSV 文件，不指定 dry_run（默认 false）
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 1
        assert data["successful"] == 1
        
        # 验证 successful_items 中的 id 不是 None（正常导入）
        for item in data["successful_items"]:
            assert item["id"] is not None
        
        # 验证 todos 确实被保存到数据库
        response = client.get("/todos/", headers=auth_headers)
        assert response.status_code == 200
        todos = response.json()
        assert len(todos) == 1
    
    def test_import_utf8_bom_file(self, auth_headers):
        """Test importing CSV file with UTF-8 BOM (Excel exported format)"""
        # 创建带有 UTF-8 BOM 的 CSV 内容
        # UTF-8 BOM 是字节序列 \xef\xbb\xbf，解码后变成 \ufeff
        # 模拟 Excel 导出的 CSV，第一列名前有 BOM
        csv_content_with_bom = '\ufefftitle,description,status\nBuy groceries,"Milk, Bread, Eggs",not_done\nFinish report,"Complete the quarterly report",done'
        
        # 上传带有 BOM 的 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test_bom.csv", csv_content_with_bom, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应（应该成功，因为 BOM 被剥离了）
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果
        assert data["total"] == 2
        assert data["successful"] == 2
        assert data["failed"] == 0
        
        # 验证 todos 确实被创建
        response = client.get("/todos/", headers=auth_headers)
        assert response.status_code == 200
        todos = response.json()
        assert len(todos) == 2
    
    def test_import_status_column_with_empty_value(self, auth_headers):
        """Test importing CSV with status column but empty values (should fail with clear error)"""
        # 创建 CSV 内容，有 status 列但某些行的 status 为空
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",not_done
Finish report,"Complete the quarterly report",
Call client,"Discuss project details",done"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果（第二行 status 为空，应该失败）
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1
        
        # 验证失败的行
        failed_items = data["failed_items"]
        assert len(failed_items) == 1
        assert "Status is required when status column is present" in failed_items[0]["errors"][0]
        
        # 验证只有 2 个 todos 被创建
        response = client.get("/todos/", headers=auth_headers)
        todos = response.json()
        assert len(todos) == 2
    
    def test_import_status_column_with_whitespace_only(self, auth_headers):
        """Test importing CSV with status column containing only whitespace (should fail)"""
        # 创建 CSV 内容，有 status 列但值为空格
        csv_content = """title,description,status
Buy groceries,"Milk, Bread, Eggs",   
Finish report,"Complete the quarterly report",not_done"""
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果（第一行 status 为空格，应该失败）
        assert data["total"] == 2
        assert data["successful"] == 1
        assert data["failed"] == 1
        
        # 验证失败的行
        failed_items = data["failed_items"]
        assert len(failed_items) == 1
        assert "Status is required when status column is present" in failed_items[0]["errors"][0]
    
    def test_import_no_status_column_uses_default(self, auth_headers):
        """Test importing CSV without status column (should use default value)"""
        # 创建 CSV 内容，没有 status 列
        csv_content = """title,description
Buy groceries,"Milk, Bread, Eggs"
Finish report,"Complete the quarterly report"
Call client,"Discuss project details" """
        
        # 上传 CSV 文件
        response = client.post(
            "/todos/import/",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应
        assert response.status_code == 200
        data = response.json()
        
        # 验证导入结果（没有 status 列，应该全部成功，使用默认值）
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0
        
        # 验证 todos 被创建且状态为默认值
        response = client.get("/todos/", headers=auth_headers)
        todos = response.json()
        assert len(todos) == 3
        for todo in todos:
            assert todo["status"] == "not_done"
    
    def test_import_file_too_large(self, auth_headers):
        """Test importing a file larger than 1MB (should return 413)"""
        # 创建一个超过 1MB 的 CSV 内容
        # 1MB = 1024 * 1024 = 1,048,576 字节
        large_content = "title,description\n"
        # 重复添加行直到超过 1MB
        while len(large_content) < 1.1 * 1024 * 1024:  # 1.1MB 确保超过限制
            large_content += 'Test Title,"This is a long description to make the file larger"\n'
        
        # 上传大文件
        response = client.post(
            "/todos/import/",
            files={"file": ("large.csv", large_content, "text/csv")},
            headers=auth_headers
        )
        
        # 检查响应（应该返回 413）
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]


class TestCSVExport:
    """Test CSV export functionality"""
    
    def create_test_todos(self, auth_headers, count=3):
        """Helper function to create test todos"""
        for i in range(count):
            response = client.post(
                "/todos/",
                json={
                    "title": f"Test Todo {i+1}",
                    "description": f"Description for todo {i+1}",
                    "status": "done" if i % 2 == 0 else "not_done"
                },
                headers=auth_headers
            )
            assert response.status_code == 200
    
    def test_export_todos(self, auth_headers):
        """Test exporting todos to CSV"""
        # 创建测试 todos
        self.create_test_todos(auth_headers, 3)
        
        # 导出 CSV
        response = client.get("/todos/export/", headers=auth_headers)
        
        # 检查响应
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        assert "todos_export.csv" in response.headers["content-disposition"]
        
        # 解析 CSV 内容
        csv_content = response.text
        
        # 使用 csv.DictReader 解析，自动处理行尾符
        reader = csv.DictReader(io.StringIO(csv_content))
        todos = list(reader)
        
        # 检查标题行
        assert "id" in reader.fieldnames
        assert "title" in reader.fieldnames
        assert "description" in reader.fieldnames
        assert "status" in reader.fieldnames
        
        # 检查数据行（3 个 todos）
        assert len(todos) == 3
        
        # 检查每个 todo 的字段
        for todo in todos:
            assert "id" in todo
            assert "title" in todo
            assert "description" in todo
            assert "status" in todo
            assert todo["title"].startswith("Test Todo")
            assert todo["description"].startswith("Description for todo")
    
    def test_export_with_status_filter(self, auth_headers):
        """Test exporting todos filtered by status"""
        # 创建测试 todos（2 个 done，1 个 not_done）
        self.create_test_todos(auth_headers, 3)
        
        # 只导出 done 状态的 todos
        response = client.get("/todos/export/?status=done", headers=auth_headers)
        
        # 检查响应
        assert response.status_code == 200
        
        # 解析 CSV 内容
        reader = csv.DictReader(io.StringIO(response.text))
        todos = list(reader)
        
        # 应该只有 2 个 done 状态的 todos
        assert len(todos) == 2
        for todo in todos:
            assert todo["status"] == "done"
    
    def test_export_empty_todos(self, auth_headers):
        """Test exporting when there are no todos"""
        # 导出 CSV（没有 todos）
        response = client.get("/todos/export/", headers=auth_headers)
        
        # 检查响应
        assert response.status_code == 200
        
        # 解析 CSV 内容
        csv_content = response.text
        lines = csv_content.strip().split("\n")
        
        # 应该只有标题行
        assert len(lines) == 1  # 只有标题行
        header = lines[0].split(",")
        assert "id" in header
        assert "title" in header
        assert "description" in header
        assert "status" in header
    
    def test_export_without_auth(self):
        """Test exporting CSV without authentication (should fail)"""
        # 导出 CSV（没有认证头）
        response = client.get("/todos/export/")
        
        # 检查响应（应该失败）
        assert response.status_code == 401
    
    def test_export_data_integrity(self, auth_headers):
        """Test that exported data matches the actual todos"""
        # 创建测试 todos
        test_todos = [
            {"title": "Todo 1", "description": "Desc 1", "status": "done"},
            {"title": "Todo 2", "description": None, "status": "not_done"},  # 空描述
            {"title": "Todo 3", "description": "Desc 3", "status": "not_done"}
        ]
        
        for todo in test_todos:
            response = client.post("/todos/", json=todo, headers=auth_headers)
            assert response.status_code == 200
        
        # 导出 CSV
        response = client.get("/todos/export/", headers=auth_headers)
        
        # 解析 CSV 内容
        reader = csv.DictReader(io.StringIO(response.text))
        exported_todos = list(reader)
        
        # 验证数量
        assert len(exported_todos) == len(test_todos)
        
        # 验证每个 todo 的数据
        for i, test_todo in enumerate(test_todos):
            exported = exported_todos[i]
            assert exported["title"] == test_todo["title"]
            assert exported["status"] == test_todo["status"]
            # 描述如果是 None 应该是空字符串
            expected_description = test_todo["description"] if test_todo["description"] else ""
            assert exported["description"] == expected_description
    
    def test_export_with_invalid_status(self, auth_headers):
        """Test exporting with invalid status parameter (should return 400)"""
        # 创建测试 todos
        self.create_test_todos(auth_headers, 2)
        
        # 尝试导出，使用非法的 status 参数
        invalid_statuses = ["invalid", "pending", "completed", "", "  "]
        
        for invalid_status in invalid_statuses:
            response = client.get(
                f"/todos/export/?status={invalid_status}", 
                headers=auth_headers
            )
            
            # 检查响应（应该返回 400）
            assert response.status_code == 400
            assert "Invalid status value" in response.json()["detail"]
            assert "not_done" in response.json()["detail"]
            assert "done" in response.json()["detail"]
    
    def test_export_with_valid_status(self, auth_headers):
        """Test that valid status values still work (not_done, done, and None)"""
        # 创建测试 todos
        self.create_test_todos(auth_headers, 3)
        
        # 测试不指定 status（None）
        response = client.get("/todos/export/", headers=auth_headers)
        assert response.status_code == 200
        
        # 测试 status=not_done
        response = client.get("/todos/export/?status=not_done", headers=auth_headers)
        assert response.status_code == 200
        
        # 测试 status=done
        response = client.get("/todos/export/?status=done", headers=auth_headers)
        assert response.status_code == 200