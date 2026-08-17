import React, { Suspense, useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, Spin } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import MainLayout from './layouts/MainLayout';
import ErrorBoundary from './components/ErrorBoundary';
import RequireAuth from './components/RequireAuth';
import { useTranslation } from 'react-i18next';

const LoginPage = React.lazy(() => import('./pages/LoginPage'));
const MapOverview = React.lazy(() => import('./pages/MapOverview'));
const Literature = React.lazy(() => import('./pages/Literature'));
const LiteratureDetail = React.lazy(() => import('./pages/LiteratureDetail'));
const Assessment = React.lazy(() => import('./pages/Assessment'));
const AntigenicMap = React.lazy(() => import('./pages/AntigenicMap'));
const Analysis = React.lazy(() => import('./pages/Analysis'));
const Report = React.lazy(() => import('./pages/Report'));
const FolderMonitor = React.lazy(() => import('./pages/FolderMonitor'));
const UserManagement = React.lazy(() => import('./pages/UserManagement'));
const Settings = React.lazy(() => import('./pages/Settings'));

const PageLoader: React.FC = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '40vh' }}>
    <Spin size="large" tip="加载中..." />
  </div>
);

/** 按页面粒度包裹的错误边界 + 懒加载 Suspense */
const PageBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ErrorBoundary page>
    <Suspense fallback={<PageLoader />}>{children}</Suspense>
  </ErrorBoundary>
);

const antdLocales: Record<string, typeof zhCN> = { zh: zhCN, en: enUS };

const App: React.FC = () => {
  const { i18n } = useTranslation();
  const [antdLocale, setAntdLocale] = useState(antdLocales[i18n.language] || zhCN);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      setAntdLocale(antdLocales[lng] || zhCN);
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => { i18n.off('languageChanged', handleLanguageChanged); };
  }, [i18n]);

  return (
    <ConfigProvider locale={antdLocale}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<PageBoundary><LoginPage /></PageBoundary>} />
          <Route element={<RequireAuth />}>
            <Route element={<MainLayout />}>
              <Route path="/" element={<PageBoundary><MapOverview /></PageBoundary>} />
              <Route path="/literature" element={<PageBoundary><Literature /></PageBoundary>} />
              <Route path="/literature/:id" element={<PageBoundary><LiteratureDetail /></PageBoundary>} />
              <Route path="/assessment" element={<PageBoundary><Assessment /></PageBoundary>} />
              <Route path="/antigenic-map" element={<PageBoundary><AntigenicMap /></PageBoundary>} />
              <Route path="/analysis" element={<PageBoundary><Analysis /></PageBoundary>} />
              <Route path="/report" element={<PageBoundary><Report /></PageBoundary>} />
              <Route path="/folders" element={<PageBoundary><FolderMonitor /></PageBoundary>} />
              <Route path="/users" element={<PageBoundary><UserManagement /></PageBoundary>} />
              <Route path="/settings" element={<PageBoundary><Settings /></PageBoundary>} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;
