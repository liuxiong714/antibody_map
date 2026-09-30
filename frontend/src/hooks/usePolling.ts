/**
 * 统一轮询 Hook（前端异步任务轮询闭环）。
 *
 * 设计要点（来自 KnowledgeGraph.tsx 成熟模式 + 经验踩坑）：
 *   - fn 用 useRef 缓存最新版本，不放进 effect 依赖数组；消费者的 useCallback 重建
 *     不会导致 interval 重启。
 *   - 定时器用 useRef 保存（timerRef），启动前先 clear 旧的，保证全程最多一个 interval。
 *   - 404 容错：Celery worker 登记 Redis 有延迟，任务刚提交时前几次轮询可能返回 404
 *     （"任务不存在"），只有连续多次仍未登记才视为过期，避免瞬时竞态误报。
 *   - attempt 计数用 useRef，不放进依赖数组。
 *   - 卸载自动清理 interval，防关闭组件后继续请求。
 *   - 停止条件 shouldStop 返回 true 时立即停止。
 *
 * 踩坑经验（ExperienceRecall ID 696342）：
 *   ❌ 把 pollingAttempts 这类状态加入 useEffect 依赖 → 每次状态变化重启定时器 → 疯狂请求
 *   ❌ 启动前不 clear 旧定时器 → 多个 interval 同时跑 → 请求风暴
 *   ✅ useRef 保存 intervalId + 启动前 clear + 卸载 clear + 计数用 ref 不用 state
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface UsePollingOptions {
  /** 轮询间隔 (ms)，默认 3000 */
  intervalMs?: number;
  /** 最大尝试次数，超过后调 onGiveUp 并停止。默认 200（3s * 200 = 10min） */
  maxAttempts?: number;
  /** 连续 404 容忍次数，超过后停止并把 giveUpReason 置 "404" */
  maxConsecutive404?: number;
  /** 判定是否已完成（返回 true → 停止轮询） */
  shouldStop?: () => boolean;
  /** 达到 maxAttempts 或超过 404 容忍时的回调 */
  onGiveUp?: (reason: 'maxAttempts' | '404') => void;
  /** 启动时是否立即执行一次 fn（默认 true） */
  runImmediately?: boolean;
}

export interface UsePollingReturn {
  /** 启动轮询（幂等：先停旧的再开新的） */
  start: () => void;
  /** 停止轮询 */
  stop: () => void;
  /** 是否正在轮询（用于 UI 展示） */
  isActive: boolean;
  /** 触发 giveUp 的原因（未触发则 null） */
  giveUpReason: 'maxAttempts' | '404' | null;
}

export function usePolling(
  fn: () => Promise<void> | void,
  opts: UsePollingOptions = {},
): UsePollingReturn {
  const {
    intervalMs = 3000,
    maxAttempts = 200,
    maxConsecutive404 = 4,
    shouldStop,
    onGiveUp,
    runImmediately = true,
  } = opts;

  const fnRef = useRef(fn);
  fnRef.current = fn;

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  const missing404Ref = useRef(0);

  const [isActive, setIsActive] = useState(false);
  const [giveUpReason, setGiveUpReason] = useState<'maxAttempts' | '404' | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsActive(false);
  }, []);

  const start = useCallback(() => {
    // 幂等：先停旧的 → 防"重复触发泄漏路径"（ExperienceRecall 696342 第一原则）
    stop();
    attemptRef.current = 0;
    missing404Ref.current = 0;
    setGiveUpReason(null);
    setIsActive(true);

    const tick = async () => {
      attemptRef.current += 1;

      if (shouldStop && shouldStop()) {
        stop();
        return;
      }

      try {
        await fnRef.current();
        missing404Ref.current = 0;

        if (shouldStop && shouldStop()) {
          stop();
          return;
        }
      } catch (e: any) {
        if (e?.response?.status === 404) {
          missing404Ref.current += 1;
          if (missing404Ref.current >= maxConsecutive404) {
            stop();
            setGiveUpReason('404');
            onGiveUp?.('404');
            return;
          }
        } else {
          missing404Ref.current = 0;
          // 其他错误不停止轮询，让下一次 interval 重试
          console.warn('[usePolling] tick error:', e?.message || e);
        }
      }

      if (attemptRef.current >= maxAttempts) {
        stop();
        setGiveUpReason('maxAttempts');
        onGiveUp?.('maxAttempts');
      }
    };

    if (runImmediately) void tick();
    timerRef.current = setInterval(() => void tick(), intervalMs);
  }, [stop, maxAttempts, maxConsecutive404, runImmediately, shouldStop, onGiveUp]);

  // 卸载清理
  useEffect(() => () => stop(), [stop]);

  return { start, stop, isActive, giveUpReason };
}
