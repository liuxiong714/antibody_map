# Tesseract OCR 部署配置指南

> 用途：扫描版 PDF / 文字层损坏 PDF 的 OCR 文字识别（如 1997 年《中国计划免疫》扫描论文）。
> 本文档整理自一次完整的 Tesseract 配置与修复过程，供后续部署新环境时参考。

---

## 1. 概述

项目使用 **Tesseract OCR** 处理以下两类 PDF：

- 扫描件（整页为图片，无文字层）
- 文字层损坏的 PDF（`PyMuPDF` 能提取到少量乱码文本，但不足以支撑数据提取）

识别流程：

```
PDF → PyMuPDF 提取文字层
     ├─ 单页文本 ≥ 100 字符 → 直接使用
     └─ 单页文本 < 100 字符（含 0）→ 渲染成图片 → Tesseract OCR（chi_sim+eng）
```

相关代码：

| 文件 | 职责 |
|---|---|
| `backend/app/core/ocr_service.py` | Tesseract 二进制/语言包探测、OCR 执行 |
| `backend/app/core/pdf_parser.py` | PDF 解析 + OCR 触发（单页阈值 `PAGE_TEXT_MIN = 100`） |
| `backend/app/config.py` | `TESSERACT_CMD` / `TESSERACT_DATA_DIR` 配置项 |
| `backend/.env` | 环境配置（复制到部署机器后按实际路径修改） |

---

## 2. 安装 Tesseract

### 2.1 Windows（winget，推荐）

```powershell
winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
```

默认安装位置：`C:\Program Files\Tesseract-OCR\tesseract.exe`（v5.x）

> 注意：winget 安装后 **不会自动加入 PATH**，但本项目代码会自动探测常见安装位置，无需手动配置 PATH。

### 2.2 Windows（手动安装）

从 [GitHub Releases](https://github.com/UB-Mannheim/tesseract/wiki) 下载安装包（选 `tesseract-ocr-w64-setup-*.exe`）。
安装时勾选 **Additional language data → Chinese (Simplified)** 可直接附带中文语言包。

### 2.3 Linux / WSL / Docker

```bash
# Debian / Ubuntu / WSL
sudo apt update && sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim

# 验证
tesseract --version && tesseract --list-langs
```

---

## 3. 安装中文语言包（chi_sim）

Tesseract 默认只带 `eng`，中文识别必须额外安装 `chi_sim.traineddata`。

### 3.1 下载语言包

| 来源 | 地址 | 体积 | 说明 |
|---|---|---|---|
| GitHub 官方（标准版，识别质量最好） | `https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata` | ~40MB | 国外访问慢 |
| jsdelivr CDN（精简版，国内速度快） | `https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/chi_sim.traineddata` | ~2.4MB | 本机实际使用此版 |

```powershell
# 国内网络推荐用 jsdelivr CDN
Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/chi_sim.traineddata" -OutFile "$env:TEMP\chi_sim.traineddata" -TimeoutSec 60
```

### 3.2 放置语言包

语言包必须放入 tesseract 可访问的 tessdata 目录，两种方式：

**方式 A：官方 tessdata 目录**（需管理员权限）

```powershell
# 放到 Program Files（需管理员 / UAC）
Copy-Item "$env:TEMP\chi_sim.traineddata" "C:\Program Files\Tesseract-OCR\tessdata\chi_sim.traineddata" -Force
```

**方式 B：用户目录**（免管理员，本机采用此方案）

```powershell
$dir = "$env:LOCALAPPDATA\Tesseract-OCR\tessdata"
New-Item -ItemType Directory -Path $dir -Force

# 注意：自定义目录中必须同时包含 eng 和 chi_sim（OCR 使用 chi_sim+eng 双语言）
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$dir\eng.traineddata" -Force
Copy-Item "$env:TEMP\chi_sim.traineddata" "$dir\chi_sim.traineddata" -Force
```

### 3.3 验证语言包

```powershell
# 官方目录
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs

# 自定义目录
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --tessdata-dir "$env:LOCALAPPDATA\Tesseract-OCR\tessdata" --list-langs
```

预期输出应包含 `chi_sim` 和 `eng`。

---

## 4. 项目配置（.env）

在 `backend/.env` 中配置（两个均可选，不配置时代码自动探测）：

```ini
# OCR - Tesseract 路径（不配置时自动探测 PATH 或 Windows 常见安装位置）
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
TESSERACT_DATA_DIR=C:\Users\admin\AppData\Local\Tesseract-OCR\tessdata
```

| 配置项 | 含义 | 默认行为 |
|---|---|---|
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | 自动探测：配置 > PATH > `Program Files` > `Program Files (x86)` > `%LOCALAPPDATA%\Programs` |
| `TESSERACT_DATA_DIR` | tessdata 语言包目录 | 自动探测：配置 > 可执行文件同目录下的 `tessdata` |

修改 `.env` 后需重启后端（`--reload` 只监听 `.py` 文件，不会热更新 `.env`）。

---

## 5. 验证 OCR 是否可用

```python
# 在 backend 目录下执行
from app.core import ocr_service
print(ocr_service.get_ocr_status())
# 预期:
# {'tesseract_available': True, 'tesseract_cmd': '...', 'tessdata_dir': '...', 'requests_available': True}
```

端到端验证（对单篇文献触发提取）：

```powershell
# 替换为实际文献 ID
Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/v1/literatures/<文献ID>/extraction" -Method POST -ContentType "application/json" -Body '{}'
Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/v1/literatures/<文献ID>/extraction/status"
```

---

## 6. 常见问题排查

### 6.1 报错 `tesseract is not installed or it's not in your PATH`

- 原因：pytesseract 找不到 tesseract 二进制
- 检查：
  - `tesseract --version`（当前终端）
  - 确认 `C:\Program Files\Tesseract-OCR\tesseract.exe` 存在
- 解决：配置 `TESSERACT_CMD` 指向完整路径，或重新安装；代码会自动探测 Windows 常见安装位置

### 6.2 报错 `Failed loading language 'chi_sim'`

- 原因：缺少中文语言包
- 解决：按第 3 节下载 `chi_sim.traineddata` 放入 tessdata 目录

### 6.3 `Access to the path ... is denied`（无法写入 Program Files）

- 解决：改用用户目录方式（方式 B），并在 `.env` 配置 `TESSERACT_DATA_DIR`

### 6.4 配置了 `TESSERACT_DATA_DIR` 但 OCR 仍找不到语言包

- 已知坑：pytesseract 在 Windows 上使用 `shlex.split(config, posix=False)` 解析 config，**双引号会被原样保留**进参数导致路径失效
- 代码已规避：`ocr_service.py` 生成的 `--tessdata-dir` 参数不带引号，同时设置 `TESSDATA_PREFIX` 环境变量兜底（兼容含空格路径）

### 6.5 扫描件 OCR 不触发（文本提取始终很短）

- 历史缺陷：旧版 `pdf_parser.py` 只对**零文本**页面做 OCR，文字层损坏页（每页有几十字符乱码）永远不触发
- 现已修复：单页文本 `< 100` 字符即判定为扫描页并交给 OCR，OCR 结果与文本页合并

### 6.6 OCR 识别出的中文乱码 / 数字错乱

- 扫描件质量低时识别精度有限，属正常现象
- 可换用标准版语言包（`tessdata` 而非 `tessdata_fast`）提升精度
- 注：百度 OCR 兜底的配置开关（`OCR_FALLBACK_TO_BAIDU` / `BAIDU_OCR_API_KEY` / `BAIDU_OCR_SECRET_KEY`）已移除，主解析链路不再通过环境变量启用百度 OCR；如需使用，可在代码中显式调用 `ocr_image(..., fallback_to_baidu=True, baidu_api_key=..., baidu_secret_key=...)`

---

## 7. 部署清单（新环境）

1. 安装 Tesseract（§2）+ 中文语言包（§3）
2. 配置 `backend/.env` 的 `TESSERACT_CMD` / `TESSERACT_DATA_DIR`（§4）
3. 重启后端，确认 `get_ocr_status()` 返回 `tesseract_available: True`（§5）
4. 对一篇扫描版文献触发提取，验证输出正常（§5）
