# V6-01: Makefile — 统一入口（E2E / 测试栈管理 / 开发辅助）
#
# 设计说明（V6-01）:
#   - E2E 不再依赖 wsl / docker exec / 生产容器；
#     pg_dump/psql 通过 E2E_PG_HOST/PORT/USER/DB/PASSWORD 直连测试栈。
#   - make e2e 跑完自动 down -v 清理，保证每次干净环境。
#   - 所有 E2E_PG_* 变量必须与 docker-compose.test.yml 一致
#     （postgres: 127.0.0.1:15432 / antibody / antibody_map_test / antibody_test_pw）.

# ===== 测试栈配置 =====
TEST_COMPOSE := docker compose -f docker-compose.test.yml
E2E_PG_HOST   := 127.0.0.1
E2E_PG_PORT   := 15432
E2E_PG_USER   := antibody
E2E_PG_DB     := antibody_map_test
E2E_PG_PW     := antibody_test_pw
E2E_REQUIRE   := 1

# 后端 DATABASE_URL 也必须指向测试库（common.py e2e_engine_session 读 settings.DATABASE_URL）
E2E_DB_URL    := postgresql+asyncpg://$(E2E_PG_USER):$(E2E_PG_PW)@$(E2E_PG_HOST):$(E2E_PG_PORT)/$(E2E_PG_DB)

export E2E_PG_HOST E2E_PG_PORT E2E_PG_USER E2E_PG_DB E2E_PG_PW E2E_REQUIRE E2E_DB_URL

.PHONY: test-up test-down test-ps e2e

# ===== 测试栈 =====
test-up:
	$(TEST_COMPOSE) up -d --wait

test-down:
	$(TEST_COMPOSE) down -v

test-ps:
	$(TEST_COMPOSE) ps

# ===== E2E 一键跑（完整三步）=====
e2e: test-up
	@echo "==> Running Alembic migrations against test DB..."
	cd backend && DATABASE_URL=$(E2E_DB_URL) alembic upgrade head
	@echo "==> Running E2E tests (all 6 suites)..."
	cd backend && E2E_PG_HOST=$(E2E_PG_HOST) \
	             E2E_PG_PORT=$(E2E_PG_PORT) \
	             E2E_PG_USER=$(E2E_PG_USER) \
	             E2E_PG_DB=$(E2E_PG_DB) \
	             E2E_PG_PASSWORD=$(E2E_PG_PW) \
	             E2E_REQUIRE=$(E2E_REQUIRE) \
	             DATABASE_URL=$(E2E_DB_URL) \
	             pytest tests/e2e/ -v --run-e2e --tb=long
	@echo "==> Cleaning up test stack..."
	$(TEST_COMPOSE) down -v
	@echo "==> DONE =="
