"""4.4：配置加固校验测试。

验证非开发环境下禁止使用默认数据库口令 / 空 MinIO 主密码，
防止 .env 漏配时静默连上弱口令库。
"""
import pytest

from app.config import Settings


def _cfg(**overrides):
    """构造 Settings，禁用 env_file（不读 .env），仅用显式值。"""
    base = dict(
        SECRET_KEY="S" * 48,
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://antibody:strongpass@localhost:5432/antibody_map",
        MINIO_ROOT_PASSWORD="M" * 32,
    )
    base.update(overrides)
    return Settings(**base, _env_file=None)


def test_dev_allows_default_db_password():
    """开发环境允许默认口令（本地 Docker Compose 场景），不报错。"""
    cfg = _cfg(
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map",
    )
    assert cfg.DATABASE_URL


def test_prod_rejects_default_db_password():
    """生产环境仍带默认口令 antibody123 时必须启动失败。"""
    with pytest.raises(ValueError, match="antibody123"):
        _cfg(
            APP_ENV="production",
            DATABASE_URL="postgresql+asyncpg://antibody:antibody123@localhost:5432/antibody_map",
        )


def test_prod_rejects_empty_minio_password():
    """生产环境配置空 MINIO_ROOT_PASSWORD 时必须启动失败。"""
    with pytest.raises(ValueError, match="MINIO_ROOT_PASSWORD"):
        _cfg(APP_ENV="production", MINIO_ROOT_PASSWORD="")


def test_prod_accepts_strong_config():
    """生产环境配好强口令时正常实例化。"""
    cfg = _cfg(APP_ENV="production")
    assert cfg.APP_ENV == "production"


def test_analysis_min_sample_thresholds_configured():
    """4.5：最小样本护栏阈值存在且为合理非负值。"""
    cfg = _cfg()
    assert getattr(cfg, "MIN_STUDIES_FOR_META", 0) >= 2
    assert getattr(cfg, "MIN_SAMPLE_FOR_META", 0) >= 1