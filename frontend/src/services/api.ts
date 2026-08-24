import axios, { AxiosRequestConfig } from 'axios';
import i18n from '../i18n';
import { clearAllApiCache } from '../lib/apiCache';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
});

// 后端标准化错误码 → i18n 文案键（轻量双语文案：后端文案不动，前端按 code 本地化）
const CODE_I18N_KEYS: Record<string, string> = {
  DATABASE_ERROR: 'error.code.DATABASE_ERROR',
  VALIDATION_ERROR: 'error.code.VALIDATION_ERROR',
  METRICS_FORBIDDEN: 'error.code.METRICS_FORBIDDEN',
};

// ===== token 存取 =====
// token/refresh_token 始终成对写入同一存储（remember → localStorage，否则 sessionStorage）。
// 通过"哪个存储已有 token"判断当前活跃存储，避免两处各留一份导致不一致。
function getActiveStore(): Storage {
  const locHasAuth = localStorage.getItem('token') !== null || localStorage.getItem('refresh_token') !== null;
  return locHasAuth ? localStorage : sessionStorage;
}

export function getStoredToken(): string | null {
  return getActiveStore().getItem('token');
}

function getStoredRefreshToken(): string | null {
  return getActiveStore().getItem('refresh_token');
}

/** 登录/刷新成功后成对保存 token 与 refresh_token，并清除另一存储中的残留副本 */
export function setStoredTokens(token: string, refreshToken: string, usePersistent?: boolean): void {
  const store =
    typeof usePersistent === 'boolean'
      ? usePersistent
        ? localStorage
        : sessionStorage
      : getActiveStore();
  const other = store === localStorage ? sessionStorage : localStorage;
  other.removeItem('token');
  other.removeItem('refresh_token');
  store.setItem('token', token);
  store.setItem('refresh_token', refreshToken);
}

/** 清除全部认证信息与前端 GET 缓存（登录失效/登出时调用） */
export function clearAuthStorage(): void {
  ['token', 'refresh_token', 'username', 'is_admin'].forEach((k) => {
    localStorage.removeItem(k);
    sessionStorage.removeItem(k);
  });
  clearAllApiCache();
}

// 解析后端错误信息：优先按 code 映射到当前语言的文案，无 code 则回退后端 message/detail
function resolveApiErrorMessage(data: any, fallback: string): string {
  const code = data?.code;
  const key = typeof code === 'string' ? CODE_I18N_KEYS[code] : undefined;
  if (key) {
    const localized = i18n.t(key);
    if (localized && localized !== key) return localized;
  }
  const detail = data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  const message = data?.message;
  if (typeof message === 'string' && message) return message;
  return fallback;
}

// 请求拦截器：自动携带 JWT 令牌
api.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ===== refresh 流程（单飞 + 排队，避免并发 401 重复刷新）=====
let isRefreshing = false;
let refreshWaiters: Array<{ resolve: (t: string) => void; reject: (e: any) => void }> = [];

/** 调用后端 /auth/refresh（用独立请求，避免走拦截器造成递归） */
async function requestRefresh(): Promise<{ token: string; refresh_token: string }> {
  const rt = getStoredRefreshToken();
  if (!rt) {
    throw new Error('NO_REFRESH_TOKEN');
  }
  const resp = await axios.post('/api/v1/auth/refresh', { refresh_token: rt }, { timeout: 20_000 });
  return resp.data?.data;
}

function runRefreshFlow(): Promise<string> {
  if (isRefreshing) {
    return new Promise<string>((resolve, reject) => refreshWaiters.push({ resolve, reject }));
  }
  isRefreshing = true;
  return requestRefresh()
    .then((data) => {
      setStoredTokens(data.token, data.refresh_token);
      refreshWaiters.forEach((w) => w.resolve(data.token));
      refreshWaiters = [];
      return data.token;
    })
    .catch((e) => {
      refreshWaiters.forEach((w) => w.reject(e));
      refreshWaiters = [];
      throw e;
    })
    .finally(() => {
      isRefreshing = false;
    });
}

function handleAuthFailure(): void {
  clearAuthStorage();
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

// 响应拦截器：自动解包 ApiResponse.data 到 resp.data，401 自动刷新重试，统一错误提示
api.interceptors.response.use(
  (resp) => {
    const body = resp.data;
    // ApiResponse 格式: { success, message, data } 或 { code, message, data } → 将 data 提升到 resp.data
    if (body && typeof body === 'object' && !Array.isArray(body) && 'data' in body && ('code' in body || 'success' in body)) {
      resp.data = body.data !== undefined ? body.data : body;
      return resp;
    }
    return resp;
  },
  (error) => {
    const original = (error?.config || {}) as AxiosRequestConfig & { _retry?: boolean };
    const status = error.response?.status;

    // 401 且持有 refresh_token，且该请求未重放过：尝试刷新后重放一次
    if (status === 401 && !original._retry && getStoredRefreshToken()) {
      original._retry = true;
      return runRefreshFlow()
        .then((newToken) => {
          original.headers = original.headers || {};
          original.headers.Authorization = `Bearer ${newToken}`;
          return api(original);
        })
        .catch((refreshErr) => {
          // 刷新失败（refresh 无效/过期/改密）：清除登录态并跳转登录
          if (refreshErr && refreshErr.message === 'NO_REFRESH_TOKEN') {
            handleAuthFailure();
          } else if (refreshErr?.response?.status === 401 || refreshErr?.response?.status === 503) {
            handleAuthFailure();
          }
          const msg = resolveApiErrorMessage(error.response?.data, error.message || '请求失败');
          console.error('[API Refresh Failed]', msg, error.response?.status);
          return Promise.reject(error);
        });
    }

    // 401 但无 refresh_token：直接退出登录
    if (status === 401) {
      handleAuthFailure();
    }

    const msg = resolveApiErrorMessage(error.response?.data, error.message || '请求失败');
    console.error('[API Error]', msg, error.response?.status, error.response?.data);
    return Promise.reject(error);
  }
);

export default api;