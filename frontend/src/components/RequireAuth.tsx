import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';

/**
 * 路由守卫：未登录用户自动跳转到 /login
 */
const RequireAuth: React.FC = () => {
  const token = localStorage.getItem('token') || sessionStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
};

export default RequireAuth;
