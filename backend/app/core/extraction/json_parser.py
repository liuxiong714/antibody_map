"""JSON 解析（从原 app.core.llm_extractor 拆分）。

包含 _smart_truncate_and_close（智能截断+补齐括号）与 _parse_json。
"""

import json
import logging
import re

logger = logging.getLogger("uvicorn")


class LLMJSONParseError(Exception):
    """F18：LLM 响应彻底无法解析为有效 JSON。

    解析失败属于"任务失败"而非"无数据可提取"，应抛此异常由任务层标记 failed
    并告警，避免静默返回空 dict 造成误判（如将异常标记为 done_no_data）。
    """


class JSONParserMixin:
    """JSON 解析：兼容 LLM 输出的多种畸形/半截 JSON。"""

    @staticmethod
    def _smart_truncate_and_close(content: str) -> str:
        """智能截断被 LLM 截断的半截 JSON，并补齐闭合括号。

        处理场景：LLM 生成到中途（如 `"gmc_u` 字段名没写完）就停止，
        导致 JSON 出现半截字段/值，同时对象和数组括号未闭合。

        算法：
        1. 逐字符扫描，维护 in_string / escape / 括号栈状态；
        2. 每当解析到"栈稳定"且不在字符串中间、且刚完成一个完整值时，
           记录为一个合法 checkpoint；
        3. 如果处于字符串中间遇到非法截断（或解析到末尾栈未闭合），
           回退到最近一个 checkpoint；
        4. 根据 checkpoint 时剩余的括号栈，逆序补 `}` 或 `]`，并补齐对象尾部可能
           遗留的尾逗号与孤立冒号。
        """
        if not content:
            return ""

        n = len(content)
        stack: list[str] = []  # 存放 '{' 或 '['
        in_string = False
        escape_next = False
        # 每个元素：(i位置, 当前栈副本)
        # 关键：checkpoint 只在 "完整值结束" 后记录（逗号、闭合括号），
        # **排除冒号**——回退到冒号位置会留下孤立的 "key": 前缀，补括号后 JSON 非法。
        checkpoints: list[tuple[int, list[str]]] = []

        i = 0
        while i < n:
            ch = content[i]

            if in_string:
                if escape_next:
                    escape_next = False
                elif ch == '\\':
                    escape_next = True
                elif ch == '"':
                    in_string = False
                # 其他字符：字符串内容，继续
                i += 1
                continue

            # 不在字符串中
            if ch == '"':
                in_string = True
            elif ch == '{':
                stack.append('{')
            elif ch == '[':
                stack.append('[')
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
                else:
                    # 不匹配：回退到上一个 checkpoint，不要再继续
                    break
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
                else:
                    break
            elif ch in (':', ',', ' ', '\t', '\n', '\r'):
                # 结构分隔符或空白
                pass
            else:
                # 普通字符（数字、null、true、false 的一部分）—— 非关键
                pass

            # checkpoint 仅在 "完整值结束" 后记录：
            # - , 表示前一个值完整，后面要跟下一个字段/元素
            # - } ] 表示对象/数组完整闭合
            # - \n \r \t 空白后紧跟值也可作为稳定点
            # 排除 : —— 冒号后面跟随值，如果在冒号处截断补括号会产生孤立的 "key":
            checkpoint_chars = set(',}]\n\r\t ')
            if ch in checkpoint_chars or i == 0:
                checkpoints.append((i, list(stack)))

            i += 1

        def _clean_and_close(prefix: str, stk: list[str]) -> str:
            """截断后清洗 + 补括号 + 兜底。"""
            # 先补括号
            suffix = ""
            for b in reversed(stk):
                suffix += '}' if b == '{' else ']'
            candidate = prefix.rstrip().rstrip(',') + suffix
            # 去掉尾逗号 ",]" / ",}"
            candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
            # 去掉孤立冒号："key":} 或 "key":]  —— 这是最常见的截断补括号后语法错误
            # 不用 look-behind（Python re 不支持可变宽度），直接替换 "key": 后跟 } 或 ] 的片段
            candidate = re.sub(r'"[^"]*"\s*:\s*(?=[}\]])', '', candidate)
            # 清理孤立逗号：如果上一步把字段删了，可能产生 {,} 或 ,}
            candidate = re.sub(r"([\{,])\s*,\s*([\}\]])", r"\1\2", candidate)
            candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
            # 清理开头多余逗号
            candidate = re.sub(r'\{,', '{', candidate)
            candidate = re.sub(r'\[,', '[', candidate)
            return candidate

        # 处理到末尾仍未闭合，或中途 break 了
        if in_string or stack:
            if in_string:
                # 在字符串中途截断：依次尝试从后往前找可用 checkpoint
                for last_i, last_stack in reversed(checkpoints):
                    prefix = content[:last_i + 1]
                    candidate = _clean_and_close(prefix, last_stack)
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        continue
                # 兜底：实在找不到有效 checkpoint，返回空对象
                logger.warning("智能截断+补齐兜底：找不到有效 checkpoint，返回 {}")
                return "{}"

            # 不在字符串中，但栈未闭合
            candidate = _clean_and_close(content, stack)
            return candidate

        # 没有问题就原样返回
        return content

    def _parse_json(self, content: str) -> dict:
        """解析 LLM 返回的 JSON"""
        if not content:
            return {}

        content_clean = content.strip()

        # 剥离 qwen3 等本地模型的 thinking 标签
        think_open = "<" + "think" + ">"
        think_close = "</" + "think" + ">"
        if think_close in content_clean:
            idx = content_clean.find(think_close)
            content_clean = content_clean[idx + len(think_close):].strip()
        if content_clean.startswith(think_open):
            content_clean = content_clean[len(think_open):].strip()

        if content_clean.startswith("```json"):
            content_clean = content_clean[7:]
        if content_clean.startswith("```"):
            content_clean = content_clean[3:]
        if content_clean.endswith("```"):
            content_clean = content_clean[:-3]
        content_clean = content_clean.strip()

        # 尝试直接解析
        try:
            return json.loads(content_clean)
        except json.JSONDecodeError as e:
            logger.warning(f"直接解析失败: {e}")

        # 尝试提取 JSON 块
        json_match = re.search(r"\{[\s\S]*\}", content_clean)
        if json_match:
            match_str = json_match.group()
            try:
                return json.loads(match_str)
            except json.JSONDecodeError as e:
                logger.warning(f"提取 JSON 块解析失败: {e}")

        # 尝试修复常见的 JSON 格式问题
        try:
            fixed = content_clean.replace("'", "\"")
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            logger.warning(f"修复单引号解析失败: {e}")

        # 尝试修复未闭合的 JSON（找到最后一个 }）
        try:
            last_brace = content_clean.rfind("}")
            if last_brace != -1:
                fixed_json = content_clean[:last_brace + 1]
                return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            logger.warning(f"修复未闭合 JSON 失败: {e}")

        # 策略：智能截断 + 补齐括号（应对被 LLM 截断的半截 JSON）
        # 逐字符扫描，记录括号栈，找到最后一个可合法解析的前缀，然后补齐闭合括号
        try:
            fixed_json = self._smart_truncate_and_close(content_clean)
            if fixed_json and fixed_json != content_clean:
                return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            logger.warning(f"智能截断+补齐解析失败: {e}")

        # 尝试使用 json.JSONDecoder 宽松模式
        try:
            import json as json_module
            decoder = json_module.JSONDecoder()
            result, _ = decoder.raw_decode(content_clean)
            return result
        except Exception as e:
            logger.warning(f"宽松模式解析失败: {e}")

        # 尝试逐字符检查问题
        try:
            import json as json_module
            for i in range(len(content_clean)):
                try:
                    json_module.loads(content_clean[:i+1])
                except json_module.JSONDecodeError:
                    continue
                else:
                    partial = content_clean[:i+1]
                    try:
                        return json_module.loads(partial)
                    except Exception:
                        logger.warning("JSON 逐字符解析失败，尝试下一个字符")
        except Exception:
            logger.warning("JSON 逐字符外层解析失败")

        # 最后兜底：从后往前逐字符删除，每步都调用 _smart_truncate_and_close 尝试补齐解析
        # 应对：即使智能截断+补齐也失败时，可能是 checkpoint 本身有问题；
        #       直接截断到前一个自然断点再补齐，暴力但有效。
        try:
            max_steps = min(2000, len(content_clean) // 2)  # 最多删 2000 字符，避免 O(N^2) 过慢
            for step in range(1, max_steps + 1):
                truncated = content_clean[:-step]
                if not truncated.strip():
                    break
                # 用 _smart_truncate_and_close 对截断内容做补齐
                fixed = self._smart_truncate_and_close(truncated)
                try:
                    result = json.loads(fixed)
                    logger.warning(
                        f"逐字符兜底截断成功：删除 {step} 字符后补齐可解析，"
                        f"原始长度 {len(content)} → 补齐后 {len(fixed)}"
                    )
                    return result
                except json.JSONDecodeError:
                    continue
        except Exception:
            logger.warning("逐字符兜底解析外层异常")

        logger.error(f"无法解析 LLM 响应为 JSON: {content[:500]}")
        logger.error(f"响应长度: {len(content)}")
        # F18：不再静默返回 {}，改为抛异常，交由任务层标记 failed 并告警
        # （避免将异常误判为 done_no_data / 无数据）。
        raise LLMJSONParseError(
            f"LLM 响应无法解析为有效 JSON（长度 {len(content)}）"
        ) from None
