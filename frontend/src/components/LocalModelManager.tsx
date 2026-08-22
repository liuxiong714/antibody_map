import React, { useEffect, useState } from 'react';
import { Modal, Table, Button, Form, Input, Space, message, Popconfirm, Tooltip, Tag } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, DesktopOutlined } from '@ant-design/icons';
import { listLocalModels, createLocalModel, updateLocalModel, deleteLocalModel } from '../services/map';
import { LocalModelConfig } from '../types';

interface Props {
  visible: boolean;
  onClose: () => void;
  onSaved: () => void;
}

const LocalModelManager: React.FC<Props> = ({ visible, onClose, onSaved }) => {
  const [configs, setConfigs] = useState<LocalModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<LocalModelConfig | null>(null);
  const [form] = Form.useForm();
  const [formVisible, setFormVisible] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const data = await listLocalModels();
      setConfigs(data);
    } catch (err) {
      console.error('[LocalModelManager] 加载失败:', err);
      message.error('加载本地模型配置失败');
    } finally { setLoading(false); }
  };

  useEffect(() => { if (visible) fetchConfigs(); }, [visible]);

  const handleAdd = () => {
    setEditing(null);
    form.resetFields();
    setFormVisible(true);
  };

  const handleEdit = (config: LocalModelConfig) => {
    setEditing(config);
    form.setFieldsValue(config);
    setFormVisible(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteLocalModel(id);
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
        await updateLocalModel(editing.id, values);
        message.success('已更新');
      } else {
        await createLocalModel(values);
        message.success('已添加');
      }
      setFormVisible(false);
      fetchConfigs();
      onSaved();
    } catch (err: any) {
      if (err?.errorFields) return; // form validation error
      message.error(err?.response?.data?.detail || '保存失败');
    } finally { setSaving(false); }
  };

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
    { title: '模型名', dataIndex: 'model_name', key: 'model', width: 180, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true, render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'is_active', key: 'active', width: 80,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag>,
    },
    { title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: LocalModelConfig) => (
        <Space>
          <Tooltip title="编辑"><Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} /></Tooltip>
          <Popconfirm title="确认删除" description="删除后不再出现在模型候选项中" onConfirm={() => handleDelete(record.id)} okText="确认" cancelText="取消">
            <Tooltip title="删除"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Modal
        title={<><DesktopOutlined /> 本地模型管理</>}
        open={visible}
        onCancel={onClose}
        width={860}
        footer={<Button onClick={onClose}>关闭</Button>}
      >
        <div style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加本地模型</Button>
        </div>
        <Table dataSource={configs} rowKey="id" columns={columns} loading={loading}
          pagination={false} size="small" locale={{ emptyText: '暂无本地模型配置' }} />
      </Modal>

      <Modal
        title={editing ? '编辑本地模型' : '添加本地模型'}
        open={formVisible}
        forceRender
        onCancel={() => setFormVisible(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input placeholder="例如: Qwen2.5:14B" />
          </Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true, message: '请输入模型名' }]}>
            <Input placeholder="例如: qwen2.5:14b（Ollama 中已 pull 的模型名）" />
          </Form.Item>
          <Form.Item name="description" label="备注说明">
            <Input.TextArea placeholder="选填，说明该模型的用途或来源" rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

export default LocalModelManager;
