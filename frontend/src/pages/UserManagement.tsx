import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Modal, Input, Switch, Space, Tag, message, Popconfirm } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined, KeyOutlined } from '@ant-design/icons';
import api from '../services/api';

interface UserItem {
  id: string;
  username: string;
  display_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
}

const UserManagement: React.FC = () => {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [resetPwdModalOpen, setResetPwdModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);
  const [newUsername, setNewUsername] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [editDisplayName, setEditDisplayName] = useState('');
  const [editIsActive, setEditIsActive] = useState(true);
  const [editIsAdmin, setEditIsAdmin] = useState(false);
  const [resetPwd, setResetPwd] = useState('');
  const [submitLoading, setSubmitLoading] = useState(false);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const res = await api.get('/auth/users');
      setUsers(res.data || []);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '加载用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const handleCreate = async () => {
    if (!newUsername.trim()) {
      message.warning('请输入用户名');
      return;
    }
    setSubmitLoading(true);
    try {
      await api.post('/auth/users', {
        username: newUsername.trim(),
        display_name: newDisplayName.trim() || null,
        is_admin: newIsAdmin,
      });
      message.success('用户创建成功，默认密码: myk123456');
      setCreateModalOpen(false);
      setNewUsername('');
      setNewDisplayName('');
      setNewIsAdmin(false);
      loadUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleEdit = (user: UserItem) => {
    setEditingUser(user);
    setEditDisplayName(user.display_name || '');
    setEditIsActive(user.is_active);
    setEditIsAdmin(user.is_admin);
    setEditModalOpen(true);
  };

  const handleEditSubmit = async () => {
    if (!editingUser) return;
    setSubmitLoading(true);
    try {
      await api.put(`/auth/users/${editingUser.id}`, {
        display_name: editDisplayName.trim() || null,
        is_active: editIsActive,
        is_admin: editIsAdmin,
      });
      message.success('用户更新成功');
      setEditModalOpen(false);
      loadUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '更新失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleResetPwd = async () => {
    if (!editingUser) return;
    if (!resetPwd || resetPwd.length < 6) {
      message.warning('密码至少 6 个字符');
      return;
    }
    setSubmitLoading(true);
    try {
      await api.put(`/auth/users/${editingUser.id}`, { password: resetPwd });
      message.success('密码重置成功');
      setResetPwdModalOpen(false);
      setResetPwd('');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '重置失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleDelete = async (user: UserItem) => {
    try {
      await api.delete(`/auth/users/${user.id}`);
      message.success('用户删除成功');
      loadUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '删除失败');
    }
  };

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name', render: (v: string | null) => v || '-' },
    {
      title: '角色',
      dataIndex: 'is_admin',
      key: 'is_admin',
      render: (v: boolean) => v ? <Tag color="blue">管理员</Tag> : <Tag>普通用户</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="red">禁用</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: UserItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Button size="small" icon={<KeyOutlined />} onClick={() => { setEditingUser(record); setResetPwdModalOpen(true); }}>重置密码</Button>
          <Popconfirm
            title="确定删除该用户？"
            onConfirm={() => handleDelete(record)}
            okText="确定"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="用户管理"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadUsers}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>新增用户</Button>
        </Space>
      }
    >
      <Table
        columns={columns}
        dataSource={users}
        rowKey="id"
        loading={loading}
        pagination={false}
      />

      {/* 新增用户弹窗 */}
      <Modal
        title="新增用户"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setCreateModalOpen(false)}>取消</Button>,
          <Button key="submit" type="primary" loading={submitLoading} onClick={handleCreate}>创建</Button>,
        ]}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
          <Input placeholder="用户名（必填）" value={newUsername} onChange={e => setNewUsername(e.target.value)} />
          <Input placeholder="显示名（选填）" value={newDisplayName} onChange={e => setNewDisplayName(e.target.value)} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Switch checked={newIsAdmin} onChange={setNewIsAdmin} />
            <span>设为管理员</span>
          </div>
          <div style={{ color: '#999', fontSize: 13 }}>新用户默认密码: myk123456</div>
        </div>
      </Modal>

      {/* 编辑用户弹窗 */}
      <Modal
        title="编辑用户"
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setEditModalOpen(false)}>取消</Button>,
          <Button key="submit" type="primary" loading={submitLoading} onClick={handleEditSubmit}>保存</Button>,
        ]}
      >
        {editingUser && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
            <Input placeholder="用户名" value={editingUser.username} disabled />
            <Input placeholder="显示名" value={editDisplayName} onChange={e => setEditDisplayName(e.target.value)} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Switch checked={editIsActive} onChange={setEditIsActive} />
              <span>启用账号</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Switch checked={editIsAdmin} onChange={setEditIsAdmin} />
              <span>管理员权限</span>
            </div>
          </div>
        )}
      </Modal>

      {/* 重置密码弹窗 */}
      <Modal
        title="重置密码"
        open={resetPwdModalOpen}
        onCancel={() => { setResetPwdModalOpen(false); setResetPwd(''); }}
        footer={[
          <Button key="cancel" onClick={() => { setResetPwdModalOpen(false); setResetPwd(''); }}>取消</Button>,
          <Button key="submit" type="primary" loading={submitLoading} onClick={handleResetPwd}>重置</Button>,
        ]}
      >
        {editingUser && (
          <div style={{ paddingTop: 8 }}>
            <p style={{ marginBottom: 8 }}>为用户 <strong>{editingUser.username}</strong> 设置新密码：</p>
            <Input.Password
              placeholder="新密码（至少 6 个字符）"
              value={resetPwd}
              onChange={e => setResetPwd(e.target.value)}
            />
          </div>
        )}
      </Modal>
    </Card>
  );
};

export default UserManagement;
