import React, { useEffect, useState } from 'react';
import { Modal, Table, Button, Form, Input, Space, message, Popconfirm, Tooltip, Tag } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, RobotOutlined, KeyOutlined, LinkOutlined } from '@ant-design/icons';
import { listRemoteModels, createRemoteModel, updateRemoteModel, deleteRemoteModel } from '../services/map';
import { ApiModelConfig } from '../types';

interface Props {
  visible: boolean;
  onClose: () => void;
  onSaved: () => void;
}

const ModelManager: React.FC<Props> = ({ visible, onClose, onSaved }) => {
  const [configs, setConfigs] = useState<ApiModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ApiModelConfig | null>(null);
  const [form] = Form.useForm();
  const [formVisible, setFormVisible] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const data = await listRemoteModels();
      setConfigs(data);
    } catch (err) { console.error('[ModelManager] 加载失败:', err); message.error('加载远程模型配置失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (visible) fetchConfigs(); }, [visible]);

  const handleAdd = () => {
    setEditing(null);
    form.resetFields();
    setFormVisible(true);
  };

  const handleEdit = (config: ApiModelConfig) => {
    setEditing(config);
    form.setFieldsValue(config);
    setFormVisible(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteRemoteModel(id);
      message.success('已删除');
      fetchConfigs();
      onSaved();
    } catch (err) { message.error('删除失败'); }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        await updateRemoteModel(editing.id, values);
        message.success('已更新');
      } else {
        await createRemoteModel(values);
        message.success('已添加');
      }
      setFormVisible(false);
      fetchConfigs();
      onSaved();
    } catch (err: any) {
      if (err?.errorFields) return; // form validation error
      message.error('保存失败');
    } finally { setSaving(false); }
  };

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    { title: '模型', dataIndex: 'model_name', key: 'model', width: 150, render: (v: string) => <Tag>{v}</Tag> },
    { title: 'API Key', dataIndex: 'api_key', key: 'key', width: 200, ellipsis: true,
      render: (v: string) => <span><KeyOutlined /> {v ? `${v.slice(0, 8)}...` : '-'}</span>,
    },
    { title: 'Base URL', dataIndex: 'base_url', key: 'url', width: 250, ellipsis: true,
      render: (v: string) => <span><LinkOutlined /> {v}</span>,
    },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true, render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'is_active', key: 'active', width: 70,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag>,
    },
    { title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: ApiModelConfig) => (
        <Space>
          <Tooltip title="编辑"><Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} /></Tooltip>
          <Popconfirm title="确认删除" description="删除后不可恢复" onConfirm={() => handleDelete(record.id)} okText="确认" cancelText="取消">
            <Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Modal
        title={<><RobotOutlined /> 远程模型管理</>}
        open={visible}
        onCancel={onClose}
        width={960}
        footer={<Button onClick={onClose}>关闭</Button>}
      >
        <div style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加远程模型</Button>
        </div>
        <Table dataSource={configs} rowKey="id" columns={columns} loading={loading}
          pagination={false} size="small" locale={{ emptyText: '暂无远程模型配置' }} />
      </Modal>

      <Modal
        title={editing ? '编辑远程模型' : '添加远程模型'}
        open={formVisible}
        onCancel={() => setFormVisible(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input placeholder="例如: DeepSeek Chat" />
          </Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true, message: '请输入模型名' }]}>
            <Input placeholder="例如: deepseek-chat" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="base_url" label="API 地址" rules={[{ required: true, message: '请输入 API 地址' }]}>
            <Input placeholder="例如: https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item name="description" label="备注说明">
            <Input.TextArea placeholder="选填，说明该模型的用途或来源" rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

export default ModelManager;