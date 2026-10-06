"""V2-16 + V4-06 差集检查: .env.example vs config.py Settings 类。

V4-06 升级: 把字段分为三类，白名单"内部/派生字段"不要求在 .env.example 文档化。

分类:
  🟢 **用户需配置**: 部署/集成时必须手动填的（数据库、Redis、MinIO、API Key 等）
  🟡 **可选覆盖**: 有合理默认值，生产可按需覆盖（超时、并发、路径等）
  ⚪ **内部字段**: 不应由用户配置（版本号、派生常量、脚本内部状态等）— 白名单豁免

使用:
    python scripts/check_env_diff.py               # dry-run: 报告真实缺失
    python scripts/check_env_diff.py --fix          # 把 🟢 + 🟡 追加为非注释行
    python scripts/check_env_diff.py --fix --force  # 强制重写所有字段（先删掉旧的 # 注释块）
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PY = ROOT / "backend" / "app" / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"

# V4-06 白名单: 不应由用户配置的内部/派生字段（完全豁免）
INTERNAL_FIELDS = {
    "APP_VERSION", "LOGIN_RATE_LIMIT_MAX", "LOGIN_RATE_LIMIT_WINDOW",
    "TRUSTED_PROXIES", "METRICS_ENABLED", "METRICS_ALLOW_IPS",
}

# V4-06 标记 "内部无需配置" 的字段（在 .env.example 里保留注释说明）
INTERNAL_TAG = "# 内部字段，无需用户配置"


def _classify(name: str) -> str:
    """返回 'green' (需配置) / 'yellow' (可选覆盖) / 'white' (内部豁免)。"""
    if name in INTERNAL_FIELDS:
        return "white"
    # 必填的基础设施连接
    green_patterns = [
        "DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "MINIO_SECRET_KEY", "MINIO_URL",
        "CRYPTO_SECRET_KEY", "CRYPTO_KEY",
        "DEEPSEEK_API_KEY", "OLLAMA_API_KEY", "ANTHROPIC_API_KEY",
        "CORS_ORIGINS", "DEFAULT_ADMIN_PASSWORD",
    ]
    for gp in green_patterns:
        if gp == name or name.startswith(gp.replace("API_KEY", "")):
            return "green"
    # 其余全部视为 yellow（有合理默认值，用户可按需覆盖）
    return "yellow"


def _extract_settings_fields(config_src: str) -> list[tuple[str, str]]:
    fields = []
    lines = config_src.split("\n")
    in_settings = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("class Settings("):
            in_settings = True
            continue
        if in_settings and stripped.startswith("class "):
            break
        if in_settings and "=" in stripped and not stripped.startswith("#"):
            m = re.match(r"(\w+)\s*:\s*.+?\s*=\s*(.+)", stripped)
            if m:
                fields.append((m.group(1), m.group(2).strip()))
            else:
                m2 = re.match(r"(\w+)\s*:", stripped)
                if m2:
                    fields.append((m2.group(1), ""))
    return fields


def _extract_env_example_vars(env_src: str) -> set[str]:
    vars_ = set()
    for line in env_src.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if re.match(r"^[A-Z][A-Z0-9_]*$", name):
                vars_.add(name)
    return vars_


def main(dry_run: bool, force: bool = False):
    config_src = CONFIG_PY.read_text(encoding="utf-8")
    env_src = ENV_EXAMPLE.read_text(encoding="utf-8")

    settings_fields = _extract_settings_fields(config_src)
    env_vars = _extract_env_example_vars(env_src)
    config_names = [f[0] for f in settings_fields]

    # 分类检查
    green_missing = []  # 用户需配置 + .env.example 里没有
    yellow_missing = []  # 可选覆盖 + .env.example 里没有
    white_exempt = []  # 内部豁免
    for name in config_names:
        cat = _classify(name)
        if cat == "white":
            white_exempt.append(name)
        elif name not in env_vars:
            if cat == "green":
                green_missing.append(name)
            else:
                yellow_missing.append(name)

    orphan_in_env = sorted(env_vars - set(config_names))

    print("=== V4-06 .env.example vs config.py Settings 差集检查 ===")
    print(f"Settings 字段总数: {len(config_names)}")
    print(f".env.example 真实变量数 (非注释): {len(env_vars)}")
    print()
    print(f"  🟢 用户需配置 (必须文档化): {len([n for n in config_names if _classify(n)=='green'])}")
    print(f"  🟡 可选覆盖   (有默认值可覆盖): {len([n for n in config_names if _classify(n)=='yellow'])}")
    print(f"  ⚪ 内部豁免   (不应由用户配置): {len(white_exempt)}")
    print()

    if green_missing:
        print(f"❌ 缺失用户需配置字段 ({len(green_missing)} 个) — 部署时可能踩坑:")
        for n in green_missing:
            d = next((d for fn, d in settings_fields if fn == n), "")
            print(f"     {n} = {d[:60]}")
    else:
        print("✅ 所有用户需配置字段已在 .env.example")

    if yellow_missing:
        print(f"\n⚠️ 可选覆盖字段缺失 ({len(yellow_missing)} 个) — 生产可按需配:")
        for n in yellow_missing:
            d = next((d for fn, d in settings_fields if fn == n), "")
            print(f"     {n} = {d[:60]}")

    if orphan_in_env:
        print(f"\n⚠️ .env.example 有但 Settings 不存在 ({len(orphan_in_env)} 个):")
        for n in orphan_in_env:
            print(f"     {n}")
    else:
        print("\n✅ .env.example 无过时变量")

    print(f"\n📊 结论: 缺失 {len(green_missing)} 必配 + {len(yellow_missing)} 可选 (白名单豁免 {len(white_exempt)} 内部字段)")

    if dry_run:
        print("\n(加 --fix 自动追加缺失行)")
        return

    if green_missing or yellow_missing:
        # --fix 模式: 先清理 V2-16 旧的注释块，然后重写
        existing = ENV_EXAMPLE.read_text(encoding="utf-8")
        # 去掉 V2-16/V4-06 自动追加的注释块（已 # 开头的）
        cleaned_lines = []
        skip_block = False
        for line in existing.split("\n"):
            stripped = line.strip()
            if "自动补齐" in stripped or stripped.startswith("# "):
                skip_block = True
                continue
            if skip_block and stripped == "":
                continue
            skip_block = False
            cleaned_lines.append(line)
        # 去掉尾部空行
        while cleaned_lines and cleaned_lines[-1].strip() == "":
            cleaned_lines.pop()

        append_lines = ["\n# === V4-06 补齐 — 用户需配置 + 可选覆盖 (非注释) ==="]
        all_missing = green_missing + yellow_missing
        for n in all_missing:
            default = next((d for fn, d in settings_fields if fn == n), "")
            cat = _classify(n)
            tag = "🟢 必配" if cat == "green" else "🟡 可选覆盖"
            append_lines.append(f"{n}={default}  # {tag}")

        append_lines.append("\n# === V4-06 白名单 — 内部字段无需配置 (不应修改) ===")
        for n in white_exempt:
            default = next((d for fn, d in settings_fields if fn == n), "")
            append_lines.append(f"# {n}={default}  # 内部字段，无需用户配置")

        cleaned_lines.extend(append_lines)
        ENV_EXAMPLE.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
        print(f"\n✅ --fix: 追加 {len(green_missing)+len(yellow_missing)} 个非注释变量 + {len(white_exempt)} 白名单注释")
    else:
        print("\n✅ --fix: 无缺失，无需修改")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="V4-06 .env.example 差集检查 + 分类补齐")
    ap.add_argument("--fix", action="store_true", help="自动追加缺失行")
    ap.add_argument("--force", action="store_true", help="强制重写（清理旧注释块）")
    args = ap.parse_args()
    main(dry_run=not args.fix, force=args.force)
