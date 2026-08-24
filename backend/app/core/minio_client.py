import io
import logging
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger("uvicorn")

_minio_client: Optional[Minio] = None


def get_minio_client() -> Optional[Minio]:
    global _minio_client
    if _minio_client is not None:
        return _minio_client

    try:
        # 凭据优先从 MINIO_ROOT_PASSWORD 读取，MINIO_SECRET_KEY 为旧名回退
        secret = settings.MINIO_ROOT_PASSWORD or settings.MINIO_SECRET_KEY
        if not secret:
            logger.warning("MinIO 未配置凭据（MINIO_ROOT_PASSWORD / MINIO_SECRET_KEY 均为空）")
            _minio_client = None
            return None
        _minio_client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=secret,
            secure=False,
        )
        # 确保 bucket 存在
        bucket = settings.MINIO_BUCKET_LITERATURE
        found = _minio_client.bucket_exists(bucket)
        if not found:
            _minio_client.make_bucket(bucket)
            logger.info(f"MinIO bucket '{bucket}' created")
        else:
            logger.info(f"MinIO bucket '{bucket}' already exists")
    except Exception as e:
        logger.warning(f"MinIO not available: {e}")
        _minio_client = None

    return _minio_client


def upload_file(file_bytes: bytes, object_name: str, content_type: str = "application/pdf") -> Optional[str]:
    client = get_minio_client()
    if client is None:
        return None
    try:
        client.put_object(
            bucket_name=settings.MINIO_BUCKET_LITERATURE,
            object_name=object_name,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )
        return object_name
    except S3Error as e:
        logger.error(f"MinIO upload failed: {e}")
        return None


def delete_file(object_name: str) -> bool:
    client = get_minio_client()
    if client is None:
        return False
    try:
        client.remove_object(
            bucket_name=settings.MINIO_BUCKET_LITERATURE,
            object_name=object_name,
        )
        return True
    except S3Error as e:
        logger.error(f"MinIO delete failed: {e}")
        return False


def get_file_url(object_name: str, expires: int = 3600) -> Optional[str]:
    client = get_minio_client()
    if client is None:
        return None
    try:
        return client.presigned_get_object(
            bucket_name=settings.MINIO_BUCKET_LITERATURE,
            object_name=object_name,
            expires=expires,
        )
    except S3Error as e:
        logger.error(f"MinIO presigned URL failed: {e}")
        return None
