#!/usr/bin/env python3
"""P2-3: 本地拖拽转换 UI（单文件）

一个独立的 PyQt5 桌面工具，用于快速将文献文件拖入并提取抗体数据点，
无需启动完整的后端服务。

功能：
- 拖拽 PDF/DOCX/TXT/HTML 等文件到窗口
- 自动解析文本 + LLM 提取数据点
- 表格展示提取结果
- 导出 CSV / JSON / 溯源 HTML
- 支持选择 LLM 模型（从 settings 读取配置）

用法：
    python tools/quick_convert.py

依赖：PyQt5, 以及 backend/ 下的 app 包（自动添加到 sys.path）
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# 将 backend 目录加入 sys.path，以便导入 app 包
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
        QComboBox, QProgressBar, QTextEdit, QSplitter, QHeaderView,
        QMessageBox, QStyle, QFrame
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData
    from PyQt5.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent
except ImportError:
    print("错误：需要 PyQt5。请运行: pip install PyQt5")
    sys.exit(1)

# 导入后端模块
try:
    from app.config import settings
    from app.core.document_parser import extract_text, ALLOWED_EXTS
    from app.core.text_preprocessor import preprocess
    from app.core.llm_extractor import LLMExtractor
    from app.core.pdf_table_parser import extract_tables_markdown
    from app.core.traceability_html import generate_traceability_html, TracePoint
except ImportError as e:
    print(f"错误：无法导入后端模块: {e}")
    print(f"请确保 backend/ 目录存在且依赖已安装: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quick_convert")


# ── 提取工作线程 ────────────────────────────────────────
class ExtractionWorker(QThread):
    """后台线程：执行文档解析 + LLM 提取"""
    progress = pyqtSignal(str)      # 日志消息
    finished_extract = pyqtSignal(list)  # 提取结果（数据点列表）
    error = pyqtSignal(str)         # 错误消息

    def __init__(self, file_path: str, model: str):
        super().__init__()
        self.file_path = file_path
        self.model = model
        self.clean_text = ""

    def run(self):
        try:
            self.progress.emit(f"正在读取文件: {self.file_path}")
            file_bytes = Path(self.file_path).read_bytes()

            ext = Path(self.file_path).suffix.lower()
            self.progress.emit(f"正在解析文件 ({ext})...")

            # 1. 文本提取
            raw_text = extract_text(file_bytes, ext)
            if not raw_text or not raw_text.strip():
                self.error.emit("文件解析后文本为空，可能为扫描件或不支持的格式")
                return
            self.progress.emit(f"文本解析完成: {len(raw_text)} 字符")

            # 2. 文本预处理
            clean_text = preprocess(raw_text)
            self.clean_text = clean_text
            self.progress.emit(f"文本预处理完成: {len(clean_text)} 字符")

            # 3. 表格提取（PDF/CAJ）
            tables_md = ""
            if ext in (".pdf", ".caj"):
                tables_md = extract_tables_markdown(file_bytes)
                if tables_md:
                    self.progress.emit(f"表格提取完成: {len(tables_md)} 字符 Markdown")

            # 4. LLM 提取
            self.progress.emit(f"正在调用 LLM ({self.model}) 提取数据点...")
            extractor = LLMExtractor(model=self.model)

            loop = asyncio.new_event_loop()
            try:
                data_points = loop.run_until_complete(
                    extractor.extract_with_retry(
                        text=clean_text,
                        language="zh",
                        tables_md=tables_md,
                        extraction_passes=settings.LLM_EXTRACTION_PASSES,
                    )
                )
            finally:
                loop.close()

            self.progress.emit(f"LLM 提取完成: {len(data_points)} 个数据点")
            self.finished_extract.emit(data_points)

        except Exception as e:
            logger.exception("提取失败")
            self.error.emit(f"提取失败: {e}")


# ── 拖拽区域 ────────────────────────────────────────────
class DropZone(QFrame):
    """可拖拽放置文件的区域"""
    fileDropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.DashedLine)
        self.setMinimumHeight(80)
        self.setStyleSheet("""
            DropZone {
                background: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 8px;
            }
            DropZone:hover {
                border-color: #3b82f6;
                background: #eff6ff;
            }
        """)
        layout = QVBoxLayout(self)
        label = QLabel("拖拽文件到此处\n（支持 PDF / DOCX / TXT / HTML / PPTX / XLSX）")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #64748b; font-size: 13px;")
        layout.addWidget(label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                DropZone {
                    background: #eff6ff;
                    border: 2px solid #3b82f6;
                    border-radius: 8px;
                }
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            DropZone {
                background: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 8px;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("""
            DropZone {
                background: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 8px;
            }
        """)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.fileDropped.emit(path)


# ── 主窗口 ──────────────────────────────────────────────
class QuickConvertWindow(QMainWindow):
    """主窗口"""

    TABLE_COLUMNS = [
        "疾病", "省份", "城市", "数据类型", "数值", "单位",
        "样本量", "年龄", "年份", "置信度", "原文依据",
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("antibody_map01 快速转换工具")
        self.setMinimumSize(900, 600)
        self.current_file = ""
        self.current_data_points: list[dict] = []
        self.current_clean_text = ""
        self.worker: Optional[ExtractionWorker] = None

        self._build_ui()
        self._load_models()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        # ── 顶部控制栏 ──
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("LLM 模型:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        top_bar.addWidget(self.model_combo)

        self.btn_open = QPushButton("打开文件")
        self.btn_open.clicked.connect(self._on_open_file)
        top_bar.addWidget(self.btn_open)

        self.btn_export_csv = QPushButton("导出 CSV")
        self.btn_export_csv.clicked.connect(lambda: self._on_export("csv"))
        self.btn_export_csv.setEnabled(False)
        top_bar.addWidget(self.btn_export_csv)

        self.btn_export_json = QPushButton("导出 JSON")
        self.btn_export_json.clicked.connect(lambda: self._on_export("json"))
        self.btn_export_json.setEnabled(False)
        top_bar.addWidget(self.btn_export_json)

        self.btn_export_html = QPushButton("溯源 HTML")
        self.btn_export_html.clicked.connect(lambda: self._on_export("html"))
        self.btn_export_html.setEnabled(False)
        top_bar.addWidget(self.btn_export_html)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # ── 拖拽区 ──
        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self._on_file_dropped)
        layout.addWidget(self.drop_zone)

        # ── 进度条 + 日志 ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        self.log_view.setStyleSheet("background: #1e293b; color: #94a3b8; font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.log_view)

        # ── 数据点表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ── 状态栏 ──
        self.statusBar().showMessage("就绪")

    def _load_models(self):
        """加载常用模型列表"""
        models = [
            "deepseek-chat",
            "deepseek-coder",
            "qwen-max",
            "qwen-plus",
            "gpt-4o",
            "gpt-4o-mini",
            "llama3",
            "qwen2.5",
            "glm4",
            "mistral",
        ]
        for m in models:
            self.model_combo.addItem(m)
        # 默认选中 settings 中配置的模型
        idx = self.model_combo.findText(settings.LLM_MODEL)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

    def _log(self, msg: str):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _on_open_file(self):
        ext_filter = " ".join(f"*{e}" for e in ALLOWED_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文献文件", "", f"文献文件 ({ext_filter})"
        )
        if path:
            self._on_file_dropped(path)

    def _on_file_dropped(self, path: str):
        ext = Path(path).suffix.lower()
        if ext not in ALLOWED_EXTS:
            QMessageBox.warning(self, "不支持的格式",
                                f"文件格式 {ext} 不支持，仅支持: {', '.join(ALLOWED_EXTS)}")
            return

        self.current_file = path
        self.drop_zone.findChild(QLabel).setText(f"已加载: {Path(path).name}")
        self._log(f"\n{'='*50}\n开始处理: {path}")

        # 禁用按钮
        self.btn_open.setEnabled(False)
        self.btn_export_csv.setEnabled(False)
        self.btn_export_json.setEnabled(False)
        self.btn_export_html.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 不确定进度

        # 启动工作线程
        model = self.model_combo.currentText()
        self.worker = ExtractionWorker(path, model)
        self.worker.progress.connect(self._log)
        self.worker.finished_extract.connect(self._on_extract_done)
        self.worker.error.connect(self._on_extract_error)
        self.worker.start()

    def _on_extract_done(self, data_points: list):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.current_data_points = data_points
        if self.worker:
            self.current_clean_text = self.worker.clean_text

        self._log(f"提取完成，共 {len(data_points)} 个数据点")

        # 填充表格
        self.table.setRowCount(len(data_points))
        for i, dp in enumerate(data_points):
            age = ""
            if dp.get("age_min") is not None and dp.get("age_max") is not None:
                age = f"{dp['age_min']}-{dp['age_max']}"
            elif dp.get("age_min") is not None:
                age = f"{dp['age_min']}+"

            row_data = [
                dp.get("disease_name", ""),
                dp.get("province", ""),
                dp.get("city", ""),
                {"seroprevalence": "阳性率", "gmc": "GMC"}.get(dp.get("data_type", ""), dp.get("data_type", "")),
                str(dp.get("positivity_rate") or dp.get("gmc_value") or ""),
                dp.get("gmc_unit", "") if dp.get("gmc_value") else "%",
                str(dp.get("sample_size") or ""),
                age,
                str(dp.get("sample_year") or dp.get("study_start_year") or ""),
                dp.get("estimate_type", "primary"),
                (dp.get("source_context") or "")[:50],
            ]
            for j, val in enumerate(row_data):
                item = QTableWidgetItem(val)
                # 低置信度高亮
                if j == 9 and val == "low":
                    item.setForeground(QColor("#dc2626"))
                self.table.setItem(i, j, item)

        # 启用导出按钮
        if data_points:
            self.btn_export_csv.setEnabled(True)
            self.btn_export_json.setEnabled(True)
            self.btn_export_html.setEnabled(True)

        self.statusBar().showMessage(f"提取完成: {len(data_points)} 个数据点")

    def _on_extract_error(self, msg: str):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self._log(f"错误: {msg}")
        QMessageBox.critical(self, "提取失败", msg)
        self.statusBar().showMessage("提取失败")

    def _on_export(self, fmt: str):
        if not self.current_data_points:
            return

        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "data_points.csv", "CSV (*.csv)")
            if path:
                self._export_csv(path)
        elif fmt == "json":
            path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", "data_points.json", "JSON (*.json)")
            if path:
                self._export_json(path)
        elif fmt == "html":
            path, _ = QFileDialog.getSaveFileName(self, "导出 HTML", "traceability.html", "HTML (*.html)")
            if path:
                self._export_html(path)

    def _export_csv(self, path: str):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(self.TABLE_COLUMNS)
        for dp in self.current_data_points:
            age = ""
            if dp.get("age_min") is not None and dp.get("age_max") is not None:
                age = f"{dp['age_min']}-{dp['age_max']}"
            writer.writerow([
                dp.get("disease_name", ""),
                dp.get("province", ""),
                dp.get("city", ""),
                dp.get("data_type", ""),
                dp.get("positivity_rate") or dp.get("gmc_value") or "",
                dp.get("gmc_unit", "") if dp.get("gmc_value") else "%",
                dp.get("sample_size") or "",
                age,
                dp.get("sample_year") or dp.get("study_start_year") or "",
                dp.get("estimate_type", "primary"),
                (dp.get("source_context") or "").replace("\n", " "),
            ])
        Path(path).write_text(output.getvalue(), encoding="utf-8-sig")
        self._log(f"CSV 已导出: {path}")
        self.statusBar().showMessage(f"CSV 导出: {path}")

    def _export_json(self, path: str):
        Path(path).write_text(
            json.dumps(self.current_data_points, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._log(f"JSON 已导出: {path}")
        self.statusBar().showMessage(f"JSON 导出: {path}")

    def _export_html(self, path: str):
        """生成溯源 HTML（如果有 clean_text）"""
        if not self.current_clean_text:
            QMessageBox.warning(self, "无法导出", "无文本内容，无法生成溯源 HTML")
            return

        # 构造 TracePoint 列表
        traces = []
        for i, dp in enumerate(self.current_data_points, start=1):
            traces.append(TracePoint(
                dp_id=f"dp-{i:04d}",
                disease=dp.get("disease_name"),
                province=dp.get("province"),
                city=dp.get("city"),
                data_type=dp.get("data_type"),
                value=dp.get("positivity_rate") or dp.get("gmc_value"),
                unit=dp.get("gmc_unit") if dp.get("gmc_value") else "%",
                sample_size=dp.get("sample_size"),
                age_min=dp.get("age_min"),
                age_max=dp.get("age_max"),
                collection_year=dp.get("sample_year") or dp.get("study_start_year"),
                confidence="medium",
                review_status="pending",
                source_page=dp.get("source_page"),
                source_context=dp.get("source_context"),
                source_char_start=dp.get("source_char_start"),
                source_char_end=dp.get("source_char_end"),
                is_grounded=bool(dp.get("is_grounded", False)),
                estimate_type=dp.get("estimate_type", "primary"),
            ))

        title = Path(self.current_file).stem
        html_content = generate_traceability_html(
            title=title,
            full_text=self.current_clean_text,
            data_points=traces,
        )
        Path(path).write_text(html_content, encoding="utf-8")
        self._log(f"溯源 HTML 已导出: {path}")
        self.statusBar().showMessage(f"HTML 导出: {path}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("antibody_map01 快速转换")

    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    window = QuickConvertWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
