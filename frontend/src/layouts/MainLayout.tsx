import React, { useState, useEffect } from 'react';
import { Layout, Menu, Dropdown, Modal, Input, Button, Space, Spin, message, type MenuProps } from 'antd';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  EnvironmentOutlined,
  BookOutlined,
  SafetyOutlined,
  BarChartOutlined,
  RadarChartOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  SearchOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  TeamOutlined,
  DownOutlined,
  LockOutlined,
  SettingOutlined,
  ApartmentOutlined,
} from '@ant-design/icons';
import LanguageSwitcher from '../components/LanguageSwitcher';
import ThemeSwitcher from '../components/ThemeSwitcher';
import api, { clearAuthStorage } from '../services/api';
import { backupDatabase } from '../services/system';

const { Sider, Content, Header } = Layout;

const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [username, setUsername] = useState('');
  // 登录时已将 is_admin 写入 storage，这里同步初始化，避免菜单项延迟出现（不同步）
  const [isAdmin, setIsAdmin] = useState<boolean>(
    () => localStorage.getItem('is_admin') === 'true' || sessionStorage.getItem('is_admin') === 'true'
  );
  const [pwdModalOpen, setPwdModalOpen] = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  // 退出登录前自动备份数据
  const [logoutModalOpen, setLogoutModalOpen] = useState(false);
  const [backupRunning, setBackupRunning] = useState(false);
  const [backupResult, setBackupResult] = useState<'success' | 'failed' | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

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
    { key: '/', icon: <EnvironmentOutlined />, label: t('nav.map') },
    { key: '/literature', icon: <BookOutlined />, label: t('nav.literature') },
    { key: '/analysis', icon: <BarChartOutlined />, label: t('nav.analysis') },
    { key: '/assessment', icon: <SafetyOutlined />, label: t('nav.assessment') },
    { key: '/antigenic-map', icon: <RadarChartOutlined />, label: t('nav.antigenicMap') },
    { key: '/report', icon: <FileTextOutlined />, label: t('nav.report') },
    { key: '/folders', icon: <FolderOpenOutlined />, label: t('nav.folders') },
    { key: '/pubmed', icon: <SearchOutlined />, label: t('nav.pubmed') },
    { key: '/knowledge-graph', icon: <ApartmentOutlined />, label: t('nav.knowledgeGraph') },
  ];

  const menuItems = isAdmin
    ? [
        ...baseMenuItems,
        { key: '/users', icon: <TeamOutlined />, label: t('nav.users') },
        { key: '/settings', icon: <SettingOutlined />, label: t('nav.settings') },
      ]
    : baseMenuItems;

  const doLogout = () => {
    clearAuthStorage();
    message.success(t('logout.success'));
    navigate('/login');
  };

  const runBackup = async () => {
    setBackupRunning(true);
    setBackupResult(null);
    try {
      await backupDatabase();
      setBackupResult('success');
      // 备份成功，自动退出登录
      setTimeout(doLogout, 800);
    } catch (err: any) {
      setBackupResult('failed');
    } finally {
      setBackupRunning(false);
    }
  };

  const handleLogout = () => {
    // 弹出备份确认对话框，默认自动执行数据库备份
    setLogoutModalOpen(true);
    runBackup();
  };

  const skipBackupAndLogout = () => {
    doLogout();
  };

  const handleChangePassword = async () => {
    if (!oldPwd || !newPwd || !confirmPwd) {
      message.warning(t('password.fillAll'));
      return;
    }
    if (newPwd !== confirmPwd) {
      message.warning(t('password.notMatch'));
      return;
    }
    if (newPwd.length < 6) {
      message.warning(t('password.tooShort'));
      return;
    }
    setPwdLoading(true);
    try {
      await api.post('/auth/change-password', {
        old_password: oldPwd,
        new_password: newPwd,
      });
      message.success(t('password.success'));
      setPwdModalOpen(false);
      setOldPwd('');
      setNewPwd('');
      setConfirmPwd('');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('password.fail'));
    } finally {
      setPwdLoading(false);
    }
  };

  const dropdownItems: MenuProps['items'] = [
    { key: 'change-pwd', icon: <KeyOutlined />, label: t('action.changePassword'), onClick: () => setPwdModalOpen(true) },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: t('action.logout'), onClick: handleLogout },
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
        <div className="sider-logo" style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ color: '#fff', fontSize: collapsed ? 14 : 18, fontWeight: 'bold', whiteSpace: 'nowrap' }}>
            {collapsed ? t('app.name.short') : t('app.name')}
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
        <Header style={{ background: 'var(--ab-bg-container)', padding: '0 24px', borderBottom: '1px solid var(--ab-border-light)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 16, color: 'var(--ab-text)' }}>{t('app.title')}</h2>
          <Space>
            <ThemeSwitcher />
            <LanguageSwitcher />
            <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <UserOutlined />
                <span>{username || t('user.unknown')}</span>
                {isAdmin && <span style={{ fontSize: 12, color: 'var(--ab-accent)' }}>({t('user.admin')})</span>}
                <DownOutlined style={{ fontSize: 12 }} />
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ margin: 16, padding: 16, background: 'var(--ab-bg-layout)', minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>

      {/* 修改密码弹窗 */}
      <Modal
        title={t('action.changePassword')}
        open={pwdModalOpen}
        onCancel={() => setPwdModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setPwdModalOpen(false)}>{t('action.cancel')}</Button>,
          <Button key="submit" type="primary" loading={pwdLoading} onClick={handleChangePassword}>{t('action.confirm')}</Button>,
        ]}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
          <Input.Password
            prefix={<KeyOutlined />}
            placeholder={t('password.old')}
            value={oldPwd}
            onChange={e => setOldPwd(e.target.value)}
          />
          <Input.Password
            prefix={<LockOutlined />}
            placeholder={t('password.new')}
            value={newPwd}
            onChange={e => setNewPwd(e.target.value)}
          />
          <Input.Password
            prefix={<LockOutlined />}
            placeholder={t('password.confirm')}
            value={confirmPwd}
            onChange={e => setConfirmPwd(e.target.value)}
          />
        </div>
      </Modal>

      {/* 退出登录前的自动备份确认弹窗 */}
      <Modal
        title={t('logout.backupTitle')}
        open={logoutModalOpen}
        closable={false}
        maskClosable={false}
        footer={[
          <Button key="cancel" onClick={() => setLogoutModalOpen(false)}>{t('action.cancel')}</Button>,
          <Button key="skip" danger loading={backupRunning} onClick={skipBackupAndLogout}>
            {t('logout.skipBackup')}
          </Button>,
        ]}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 8 }}>
          {backupRunning && <Spin />}
          <span>
            {backupRunning
              ? t('logout.backupRunning')
              : backupResult === 'success'
                ? `${t('logout.backupSuccess')}，${t('logout.backupLoggingOut')}`
                : backupResult === 'failed'
                  ? t('logout.backupFailed')
                  : t('logout.backupRunning')}
          </span>
        </div>
      </Modal>
    </Layout>
  );
};

export default MainLayout;
