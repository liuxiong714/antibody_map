import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './layouts/MainLayout';
import MapOverview from './pages/MapOverview';
import Literature from './pages/Literature';
import LiteratureDetail from './pages/LiteratureDetail';
import Assessment from './pages/Assessment';
import Analysis from './pages/Analysis';
import Report from './pages/Report';

const App: React.FC = () => (
  <ConfigProvider locale={zhCN}>
    <BrowserRouter>
      <Routes>
        <Route element={<MainLayout />}>
          <Route path="/" element={<MapOverview />} />
          <Route path="/literature" element={<Literature />} />
          <Route path="/literature/:id" element={<LiteratureDetail />} />
          <Route path="/assessment" element={<Assessment />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/report" element={<Report />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </ConfigProvider>
);

export default App;
