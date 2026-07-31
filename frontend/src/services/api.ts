import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
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
    const msg = error.response?.data?.detail || error.message || '请求失败';
    console.error('[API Error]', msg);
    return Promise.reject(error);
  }
);

export default api;
