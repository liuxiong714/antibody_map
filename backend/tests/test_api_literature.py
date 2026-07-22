import pytest
import httpx
from httpx import ASGITransport
from app.main import app


class TestLiteratureAPI:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_health_check(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["service"] == "antibody-map-api"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_literatures_default(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/literatures")
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_literatures_with_pagination(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/literatures?page=1&page_size=10")
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) <= 10

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_literatures_with_keyword(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/literatures?keyword=test")
            assert response.status_code == 200

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_nonexistent_literature(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            fake_id = "00000000-0000-0000-0000-000000000000"
            response = await client.get(f"/api/v1/literatures/{fake_id}")
            assert response.status_code == 404
            assert "文献不存在" in response.json()["detail"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_upload_literature_invalid_file_type(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/literatures/upload",
                files={"file": ("test.txt", b"not a pdf", "text/plain")},
            )
            assert response.status_code == 400
            assert "只支持 PDF 文件" in response.json()["detail"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_upload_literature_missing_file(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/literatures/upload")
            assert response.status_code == 422