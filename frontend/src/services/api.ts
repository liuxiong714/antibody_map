import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
});

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败';
    console.error('[API Error]', msg);
    return Promise.reject(error);
  }
);

export default api;
