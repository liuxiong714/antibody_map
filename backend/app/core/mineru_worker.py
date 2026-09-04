"""MinerU PDF 解析独立子进程入口（随 worker 镜像打包）。

背景：Celery prefork 的 ForkPoolWorker 是 daemonic 进程，Python multiprocessing
禁止 daemonic 进程再派生子进程；而 MinerU 推理内部会 spawn 子进程，导致
"daemonic processes are not allowed to have children" 异常、静默回退 PyMuPDF。

本模块以独立进程（非 daemonic）运行，可正常派生子进程；pdf_parser 通过
subprocess 调用它，从而在 Celery 任务中也能完整使用 MinerU。

用法: python -m app.core.mineru_worker <pdf_path>
stdout 输出结构化 Markdown；失败时 stderr 输出错误并以非 0 退出码退出。
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("mineru_worker")


def main() -> int:
    # worker 容器根文件系统只读（docker-compose read_only: true），MinerU/ModelScope
    # 默认会在 /root/.modelscope、/root/mineru.json 写缓存与配置而失败。
    # 这里把缓存与配置目录全部重定向到已挂载的可写目录 /root/.cache/modelscope，
    # 使 MinerU 增强解析可用（模型缓存也已本地固化在该挂载点）。
    writable_cache = "/root/.cache/modelscope"
    # ModelScope 模型缓存目录（默认 ~/.cache/modelscope，本挂载点即默认路径）
    os.environ.setdefault("MODELSCOPE_CACHE", writable_cache)
    # ModelScope SDK 配置目录（默认 ~/.modelscope → /root/.modelscope 只读不可写）。
    # 重定向到可写挂载点下的子目录，避免 CacheError: Failed to create SDK directories
    os.environ.setdefault("MODELSCOPE_HOME", f"{writable_cache}/modelscope_home")
    # MinerU 工具配置文件（默认 ~/mineru.json → /root/mineru.json 只读不可写）。
    # 该变量支持绝对路径，直接指向可写挂载点
    os.environ.setdefault("MINERU_TOOLS_CONFIG_JSON", f"{writable_cache}/mineru.json")
    # PyTorch/Triton 编译缓存（默认 ~/.triton → /root/.triton 只读不可写）。
    # 重定向到可写挂载点，避免 MinerU 子进程 OSError: Read-only file system
    os.environ.setdefault("TRITON_CACHE_DIR", f"{writable_cache}/triton_cache")
    # HuggingFace 缓存（默认 ~/.cache/huggingface），一并重定向到可写挂载点
    os.environ.setdefault("HF_HOME", f"{writable_cache}/huggingface")
    os.makedirs(writable_cache, exist_ok=True)

    if len(sys.argv) < 2:
        print("usage: python -m app.core.mineru_worker <pdf_path>", file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"[mineru_worker] 文件不存在: {pdf_path}", file=sys.stderr)
        return 2
    file_bytes = pdf_path.read_bytes()

    # 延迟导入，仅在使用时加载重型依赖（torch/mineru）
    from mineru.backend.hybrid.hybrid_analyze import doc_analyze
    from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make
    from mineru.utils.enum_class import MakeMode

    middle_json, _model_list = doc_analyze(
        pdf_bytes=file_bytes,
        image_writer=None,
        backend="transformers",
        parse_method="auto",
    )
    pdf_info = middle_json.get("pdf_info", [])
    if not pdf_info:
        print("[mineru_worker] 解析结果为空", file=sys.stderr)
        return 3

    markdown_text = union_make(pdf_info, MakeMode.MM_MD, "")
    if not markdown_text or not markdown_text.strip():
        print("[mineru_worker] union_make 输出为空", file=sys.stderr)
        return 4

    sys.stdout.write(markdown_text)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[mineru_worker] 失败: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
