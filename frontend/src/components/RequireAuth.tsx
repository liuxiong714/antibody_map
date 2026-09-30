import React, { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import api, { clearAuthStorage, getStoredToken } from '../services/api';

/**
 * 路由守卫：未登录或 token 已失效时跳转 /login。
 * C9：不再仅凭 token 存在性放行——先调 /auth/me 做后端校验，
 * 校验期间显示加载态，避免"过期/伪造 token 短暂闪现受保护页面"。
 */
const RequireAuth: React.FC = () => {
  const location = useLocation();
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const token = getStoredToken();
    if (!token) {
      setChecking(false);
      return;
    }
    // 后端校验 token（401 时 api 拦截器会尝试 refresh，仍失败则自动清登录态并跳转）
    api
      .get('/auth/me')
      .then(() => {
        if (!cancelled) setValid(true);
      })
      .catch(() => {
        if (!cancelled) clearAuthStorage();
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  if (checking) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="验证登录状态...">
          <div style={{ height: 40 }} />
        </Spin>
      </div>
    );
  }

  if (!valid) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
};

export default RequireAuth;
