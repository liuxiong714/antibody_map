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
import sys
from pathlib import Path

logger = logging.getLogger("mineru_worker")


def main() -> int:
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
