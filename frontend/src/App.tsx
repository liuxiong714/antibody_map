import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, Spin } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './layouts/MainLayout';
import ErrorBoundary from './components/ErrorBoundary';
import RequireAuth from './components/RequireAuth';

const LoginPage = React.lazy(() => import('./pages/LoginPage'));
const MapOverview = React.lazy(() => import('./pages/MapOverview'));
const Literature = React.lazy(() => import('./pages/Literature'));
const LiteratureDetail = React.lazy(() => import('./pages/LiteratureDetail'));
const Assessment = React.lazy(() => import('./pages/Assessment'));
const Analysis = React.lazy(() => import('./pages/Analysis'));
const Report = React.lazy(() => import('./pages/Report'));
const FolderMonitor = React.lazy(() => import('./pages/FolderMonitor'));
const UserManagement = React.lazy(() => import('./pages/UserManagement'));

const PageLoader: React.FC = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '40vh' }}>
    <Spin size="large" />
  </div>
);

const App: React.FC = () => (
  <ConfigProvider locale={zhCN}>
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<MainLayout />}>
                <Route path="/" element={<MapOverview />} />
                <Route path="/literature" element={<Literature />} />
                <Route path="/literature/:id" element={<LiteratureDetail />} />
                <Route path="/assessment" element={<Assessment />} />
                <Route path="/analysis" element={<Analysis />} />
                <Route path="/report" element={<Report />} />
                <Route path="/folders" element={<FolderMonitor />} />
                <Route path="/users" element={<UserManagement />} />
              </Route>
            </Route>
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  </ConfigProvider>
);

export default App;
