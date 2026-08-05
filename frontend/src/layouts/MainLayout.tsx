import React, { useState } from 'react';
import { Layout, Menu } from 'antd';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  EnvironmentOutlined,
  BookOutlined,
  SafetyOutlined,
  BarChartOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons';

const { Sider, Content, Header } = Layout;

const menuItems = [
  { key: '/', icon: <EnvironmentOutlined />, label: '地图总览' },
  { key: '/literature', icon: <BookOutlined />, label: '文献管理' },
  { key: '/analysis', icon: <BarChartOutlined />, label: '数据分析' },
  { key: '/assessment', icon: <SafetyOutlined />, label: '免疫屏障评估' },
  { key: '/report', icon: <FileTextOutlined />, label: '报告生成' },
  { key: '/folders', icon: <FolderOpenOutlined />, label: '文件夹监控' },
];

const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey = location.pathname === '/' ? '/' : '/' + location.pathname.split('/')[1];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={200}
      >
        <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ color: '#fff', fontSize: collapsed ? 14 : 18, fontWeight: 'bold', whiteSpace: 'nowrap' }}>
            {collapsed ? '抗体' : '抗体地图'}
          </span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0' }}>
          <h2 style={{ margin: 0, fontSize: 16, color: '#333' }}>血清抗体流行病学数据可视化平台</h2>
        </Header>
        <Content style={{ margin: 16, padding: 16, background: '#f5f5f5', minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};

export default MainLayout;
