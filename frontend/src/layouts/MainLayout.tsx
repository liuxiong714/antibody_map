import React, { useState, useEffect } from 'react';
import { Layout, Menu, Dropdown, Modal, Input, Button, Space, message, Spin, type MenuProps } from 'antd';
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
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import LanguageSwitcher from '../components/LanguageSwitcher';
import api from '../services/api';

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
  // 登出备份弹窗状态：idle=已触发待确认 / running=备份执行中 / success=备份完成 / error=备份失败
  const [backupModalOpen, setBackupModalOpen] = useState(false);
  const [backupState, setBackupState] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [backupInfo, setBackupInfo] = useState<any>(null);
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
    { key: '/antigenic-map', icon: <RadarChartOutlined />, label: '抗原图谱' },
    { key: '/report', icon: <FileTextOutlined />, label: t('nav.report') },
    { key: '/folders', icon: <FolderOpenOutlined />, label: t('nav.folders') },
    { key: '/pubmed', icon: <SearchOutlined />, label: t('nav.pubmed') },
    { key: '/settings', icon: <SettingOutlined />, label: t('nav.settings') },
  ];

  const menuItems = isAdmin
    ? [
        ...baseMenuItems,
        { key: '/users', icon: <TeamOutlined />, label: t('nav.users') },
      ]
    : baseMenuItems;

  // 真正的登出：清空本地凭据并跳转登录页
  const performLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('username');
    message.success(t('logout.success'));
    navigate('/login');
  };

  // 关闭备份弹窗并登出（不执行备份）
  const doLogoutSkippingBackup = () => {
    setBackupModalOpen(false);
    performLogout();
  };

  // 触发登出备份：自动开始执行，除非用户点击"跳过备份"
  const handleLogout = () => {
    setBackupModalOpen(true);
    setBackupState('running');
    setBackupInfo(null);
    api
      .post('/system/backup')
      .then(res => {
        const data = res.data?.data || res.data || {};
        setBackupInfo(data);
        setBackupState('success');
        // 备份成功后短暂停留展示结果，再自动登出
        setTimeout(performLogout, 1200);
      })
      .catch(err => {
        setBackupState('error');
        const detail = err?.response?.data?.detail || err?.message || '备份失败';
        setBackupInfo({ detail });
        // 备份失败不阻塞登出：短暂展示后仍自动退出
        setTimeout(performLogout, 1500);
      });
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
        <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
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
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 16, color: '#333' }}>{t('app.title')}</h2>
          <Space>
            <LanguageSwitcher />
            <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <UserOutlined />
                <span>{username || t('user.unknown')}</span>
                {isAdmin && <span style={{ fontSize: 12, color: '#1677ff' }}>({t('user.admin')})</span>}
                <DownOutlined style={{ fontSize: 12 }} />
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ margin: 16, padding: 16, background: '#f5f5f5', minHeight: 280 }}>
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

      {/* 退出登录前自动备份弹窗 */}
      <Modal
        title={t('logout.backupTitle')}
        open={backupModalOpen}
        closable={false}
        maskClosable={false}
        keyboard={false}
        footer={[
          <Button
            key="skip"
            danger
            onClick={doLogoutSkippingBackup}
            disabled={backupState === 'success'}
            loading={backupState === 'running'}
          >
            {t('logout.skipBackup')}
          </Button>,
        ]}
      >
        {backupState === 'running' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0' }}>
            <Spin />
            <span>{t('logout.backupRunning')}</span>
          </div>
        )}

        {backupState === 'success' && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '8px 0',
            }}
          >
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 18, marginTop: 2 }} />
            <div>
              <div>{t('logout.backupSuccess')}</div>
              {backupInfo?.filename && (
                <div style={{ marginTop: 6, color: 'rgba(0,0,0,0.65)' }}>
                  {backupInfo.filename}（{(backupInfo.size / 1024 / 1024).toFixed(2)} MB）
                </div>
              )}
              <div style={{ marginTop: 4, color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                {t('logout.backupLoggingOut')}
              </div>
            </div>
          </div>
        )}

        {backupState === 'error' && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '8px 0',
            }}
          >
            <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: 18, marginTop: 2 }} />
            <div>
              <div>{backupInfo?.detail ? `${t('logout.backupFailed')}：${backupInfo.detail}` : t('logout.backupFailed')}</div>
              <div style={{ marginTop: 4, color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                {t('logout.backupLoggingOut')}
              </div>
            </div>
          </div>
        )}
      </Modal>
    </Layout>
  );
};

export default MainLayout;
