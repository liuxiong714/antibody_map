import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
});

// 请求拦截器：自动携带 JWT 令牌
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token') || sessionStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：自动解包 ApiResponse.data 到 resp.data，统一错误提示
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
    // 401 未授权：清除 token 并跳转登录页
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('username');
      localStorage.removeItem('is_admin');
      sessionStorage.removeItem('token');
      sessionStorage.removeItem('username');
      sessionStorage.removeItem('is_admin');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    const msg = error.response?.data?.detail || error.message || '请求失败';
    console.error('[API Error]', msg);
    return Promise.reject(error);
  }
);

export default api;
