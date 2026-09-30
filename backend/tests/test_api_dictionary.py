import pytest
import httpx
from httpx import ASGITransport
from app.main import app


class TestDictionaryAPI:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_diseases(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/dictionary/diseases")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "data" in data
            diseases = data["data"]
            assert len(diseases) > 0
            assert all("key" in d and "name_cn" in d for d in diseases)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_provinces(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/dictionary/provinces")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "data" in data
            provinces = data["data"]
            assert len(provinces) == 34
            assert all("code" in p and "name" in p for p in provinces)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_methods(self):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/dictionary/methods")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "data" in data
            methods = data["data"]
            assert len(methods) > 0
            assert all("key" in m and "name_cn" in m for m in methods)