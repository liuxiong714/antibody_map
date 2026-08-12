import React, { useState, useEffect } from 'react';
import { Layout, Menu, Dropdown, Modal, Input, Button, Space, message, type MenuProps } from 'antd';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  EnvironmentOutlined,
  BookOutlined,
  SafetyOutlined,
  BarChartOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  TeamOutlined,
  DownOutlined,
  LockOutlined,
} from '@ant-design/icons';
import api from '../services/api';

const { Sider, Content, Header } = Layout;

const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [username, setUsername] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [pwdModalOpen, setPwdModalOpen] = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    // 从 storage 获取用户名
    const name = localStorage.getItem('username') || sessionStorage.getItem('username') || '';
    setUsername(name);
    // 查询当前用户是否是管理员
    api.get('/auth/me').then(res => {
      setUsername(res.data.display_name || res.data.username);
      setIsAdmin(res.data.is_admin);
    }).catch(() => {});
  }, []);

  const selectedKey = location.pathname === '/' ? '/' : '/' + location.pathname.split('/')[1];

  const baseMenuItems = [
    { key: '/', icon: <EnvironmentOutlined />, label: '地图总览' },
    { key: '/literature', icon: <BookOutlined />, label: '文献管理' },
    { key: '/analysis', icon: <BarChartOutlined />, label: '数据分析' },
    { key: '/assessment', icon: <SafetyOutlined />, label: '免疫屏障评估' },
    { key: '/report', icon: <FileTextOutlined />, label: '报告生成' },
    { key: '/folders', icon: <FolderOpenOutlined />, label: '文件夹监控' },
  ];

  const menuItems = isAdmin
    ? [...baseMenuItems, { key: '/users', icon: <TeamOutlined />, label: '用户管理' }]
    : baseMenuItems;

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('username');
    message.success('已退出登录');
    navigate('/login');
  };

  const handleChangePassword = async () => {
    if (!oldPwd || !newPwd || !confirmPwd) {
      message.warning('请填写所有字段');
      return;
    }
    if (newPwd !== confirmPwd) {
      message.warning('两次输入的新密码不一致');
      return;
    }
    if (newPwd.length < 6) {
      message.warning('新密码至少 6 个字符');
      return;
    }
    setPwdLoading(true);
    try {
      await api.post('/auth/change-password', {
        old_password: oldPwd,
        new_password: newPwd,
      });
      message.success('密码修改成功');
      setPwdModalOpen(false);
      setOldPwd('');
      setNewPwd('');
      setConfirmPwd('');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '密码修改失败');
    } finally {
      setPwdLoading(false);
    }
  };

  const dropdownItems: MenuProps['items'] = [
    { key: 'change-pwd', icon: <KeyOutlined />, label: '修改密码', onClick: () => setPwdModalOpen(true) },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
  ];

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
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 16, color: '#333' }}>血清抗体流行病学数据可视化平台</h2>
          <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <UserOutlined />
              <span>{username || '用户'}</span>
              {isAdmin && <span style={{ fontSize: 12, color: '#1677ff' }}>(管理员)</span>}
              <DownOutlined style={{ fontSize: 12 }} />
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 16, padding: 16, background: '#f5f5f5', minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>

      {/* 修改密码弹窗 */}
      <Modal
        title="修改密码"
        open={pwdModalOpen}
        onCancel={() => setPwdModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setPwdModalOpen(false)}>取消</Button>,
          <Button key="submit" type="primary" loading={pwdLoading} onClick={handleChangePassword}>确认修改</Button>,
        ]}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
          <Input.Password
            prefix={<KeyOutlined />}
            placeholder="原密码"
            value={oldPwd}
            onChange={e => setOldPwd(e.target.value)}
          />
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="新密码（至少 6 个字符）"
            value={newPwd}
            onChange={e => setNewPwd(e.target.value)}
          />
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="确认新密码"
            value={confirmPwd}
            onChange={e => setConfirmPwd(e.target.value)}
          />
        </div>
      </Modal>
    </Layout>
  );
};

export default MainLayout;
