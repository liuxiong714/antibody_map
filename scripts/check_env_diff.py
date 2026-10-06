"""V2-16 差集检查: .env.example vs config.py Settings 类。

找出:
  1) config.py Settings 里有但 .env.example 没文档化的字段（配置裸奔）
  2) .env.example 里有但 Settings 里不存在的变量（过时/拼写错）

使用:
    python scripts/check_env_diff.py          # 默认 dry-run，只报告
    python scripts/check_env_diff.py --fix    # 自动追加缺失行到 .env.example（不删除任何已有行）
"""
import argparse
import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PY = ROOT / "backend" / "app" / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"


def _extract_settings_fields(config_src: str) -> list[tuple[str, str]]:
    """从 config.py 解析 Settings 类字段列表 [(name, default_or_type), ...]。"""
    fields = []
    # 找 class Settings(BaseSettings): 的块
    lines = config_src.split("\n")
    in_settings = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("class Settings("):
            in_settings = True
            continue
        if in_settings and stripped.startswith("class "):
            break  # Settings 类结束
        if in_settings and "=" in stripped and not stripped.startswith("#"):
            # 形如: FIELD_NAME: TYPE = default_value
            # 或: FIELD_NAME: TYPE
            m = re.match(r"(\w+)\s*:\s*.+?\s*=\s*(.+)", stripped)
            if m:
                fname = m.group(1)
                fdefault = m.group(2).strip()
                fields.append((fname, fdefault))
            else:
                m2 = re.match(r"(\w+)\s*:", stripped)
                if m2:
                    fields.append((m2.group(1), ""))
    return fields


def _extract_env_example_vars(env_src: str) -> list[str]:
    """从 .env.example 提取 VAR_NAME 列表（跳过注释和空行）。"""
    vars_ = []
    for line in env_src.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 只取左边 = 号前的变量名
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if re.match(r"^[A-Z][A-Z0-9_]*$", name):
                vars_.append(name)
    return vars_


def main(dry_run: bool):
    config_src = CONFIG_PY.read_text(encoding="utf-8")
    env_src = ENV_EXAMPLE.read_text(encoding="utf-8")

    settings_fields = _extract_settings_fields(config_src)
    env_vars = set(_extract_env_example_vars(env_src))

    config_names = [f[0] for f in settings_fields]
    missing_in_env = [n for n in config_names if n not in env_vars]
    orphan_in_env = sorted(env_vars - set(config_names))

    print(f"=== V2-16 .env.example vs config.py Settings 差集检查 ===")
    print(f"Settings 字段总数: {len(config_names)}")
    print(f".env.example 变量数: {len(env_vars)}")

    if missing_in_env:
        print(f"\n⚠️ config.py 有但 .env.example 缺失 ({len(missing_in_env)} 个):")
        for n in missing_in_env:
            # 找默认值
            default = next((d for fn, d in settings_fields if fn == n), "")
            print(f"   {n} = {default}")
    else:
        print("\n✅ config.py 全部字段已在 .env.example 文档化")

    if orphan_in_env:
        print(f"\n⚠️ .env.example 有但 Settings 不存在 ({len(orphan_in_env)} 个):")
        for n in orphan_in_env:
            print(f"   {n}")
    else:
        print("\n✅ .env.example 无过时变量")

    if dry_run:
        print("\n(加 --fix 自动追加缺失行)")
        return

    # --fix 模式：只追加缺失行，不删除
    if missing_in_env:
        append_lines = ["\n# === V2-16 自动补齐 (fix_env_diff --fix) ==="]
        for n in missing_in_env:
            default = next((d for fn, d in settings_fields if fn == n), "")
            append_lines.append(f"# {n}={default}  # 默认已在 Settings 类定义")
        append_lines.append("\n")
        with open(ENV_EXAMPLE, "a", encoding="utf-8") as f:
            f.write("\n".join(append_lines))
        print(f"\n✅ 已追加 {len(missing_in_env)} 行到 .env.example 末尾（# 注释形式）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="V2-16 差集检查")
    ap.add_argument("--fix", action="store_true", help="追加缺失行到 .env.example")
    args = ap.parse_args()
    main(dry_run=not args.fix)
