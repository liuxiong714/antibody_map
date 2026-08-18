import React, { useState, useCallback, useEffect } from 'react';
import {
  Card, Table, Button, Space, Modal, Form, Input, InputNumber, Switch, Select,
  message, Popconfirm, Tag, Tooltip, Drawer, Alert, Statistic, Row, Col, Empty,
} from 'antd';
import {
  PlusOutlined, ReloadOutlined, FolderOpenOutlined, ScanOutlined,
  EditOutlined, DeleteOutlined, FileTextOutlined, EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  listFolders, createFolder, updateFolder, deleteFolder, scanFolder, listFolderFiles,
} from '../services/folderMonitor';
import { listLiterature } from '../services/literature';
import { buildModelOptions, ExtendedModelOption } from '../utils/modelOptions';
import type { MonitoredFolder, MonitoredFolderCreate, MonitoredFile, Literature } from '../types';

const FolderMonitorPage: React.FC = () => {
  const [folders, setFolders] = useState<MonitoredFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingFolder, setEditingFolder] = useState<MonitoredFolder | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [scanningIds, setScanningIds] = useState<Set<string>>(new Set());
  const [form] = Form.useForm();
  const [modelOptions, setModelOptions] = useState<ExtendedModelOption[]>([]);

  useEffect(() => {
    buildModelOptions().then(setModelOptions);
  }, []);

  // 文件记录 Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerFolder, setDrawerFolder] = useState<MonitoredFolder | null>(null);
  const [files, setFiles] = useState<MonitoredFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);

  // 文献标题映射
  const [litMap, setLitMap] = useState<Record<string, Literature>>({});

  const fetchFolders = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listFolders();
      setFolders(data);
    } catch {
      message.error('加载文件夹列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchFolders(); }, [fetchFolders]);

  // 定时刷新（10秒）
  useEffect(() => {
    const timer = setInterval(fetchFolders, 10000);
    return () => clearInterval(timer);
  }, [fetchFolders]);

  const handleAdd = () => {
    setEditingFolder(null);
    form.resetFields();
    form.setFieldsValue({
      enabled: true,
      scan_interval_seconds: 300,
      auto_extract: true,
    });
    setModalOpen(true);
  };

  const handleEdit = (record: MonitoredFolder) => {
    setEditingFolder(record);
    form.setFieldsValue({
      name: record.name,
      folder_path: record.folder_path,
      enabled: record.enabled,
      scan_interval_seconds: record.scan_interval_seconds,
      file_extensions: record.file_extensions,
      auto_extract: record.auto_extract,
      extraction_model: record.extraction_model,
      extraction_api_key: record.extraction_api_key,
      extraction_base_url: record.extraction_base_url,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const payload: MonitoredFolderCreate = {
        name: values.name,
        folder_path: values.folder_path,
        enabled: values.enabled,
        scan_interval_seconds: values.scan_interval_seconds,
        file_extensions: values.file_extensions || null,
        auto_extract: values.auto_extract,
        extraction_model: values.extraction_model || null,
        extraction_api_key: values.extraction_api_key || null,
        extraction_base_url: values.extraction_base_url || null,
      };
      if (editingFolder) {
        await updateFolder(editingFolder.id, payload);
        message.success('更新成功');
      } else {
        await createFolder(payload);
        message.success('添加成功');
      }
      setModalOpen(false);
      fetchFolders();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(detail || '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteFolder(id);
      message.success('删除成功');
      fetchFolders();
    } catch {
      message.error('删除失败');
    }
  };

  const handleScan = async (id: string) => {
    setScanningIds(prev => new Set(prev).add(id));
    try {
      await scanFolder(id);
      message.success('扫描已启动，请稍后在列表中查看结果');
      fetchFolders();
      // 15秒后自动清除扫描中状态（依赖自动刷新检测真实状态）
      setTimeout(() => {
        setScanningIds(prev => { const s = new Set(prev); s.delete(id); return s; });
        fetchFolders();
      }, 15000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(detail || '扫描启动失败');
      setScanningIds(prev => { const s = new Set(prev); s.delete(id); return s; });
    }
  };

  const handleToggleEnabled = async (record: MonitoredFolder, enabled: boolean) => {
    try {
      await updateFolder(record.id, { enabled });
      message.success(enabled ? '已启用监控' : '已暂停监控');
      fetchFolders();
    } catch {
      message.error('更新失败');
    }
  };

  const handleViewFiles = async (record: MonitoredFolder) => {
    setDrawerFolder(record);
    setDrawerOpen(true);
    setFilesLoading(true);
    try {
      const data = await listFolderFiles(record.id);
      setFiles(data);

      // 获取关联文献标题
      const litIds = data.filter(f => f.literature_id).map(f => f.literature_id!);
      if (litIds.length > 0) {
        const map: Record<string, Literature> = {};
        let page = 1;
        let total = Infinity;
        while (Object.keys(map).length < litIds.length && page <= 10) {
          const resp = await listLiterature({ page, page_size: 100 });
          total = resp.total;
          resp.items.forEach((l) => {
            if (litIds.includes(l.id)) map[l.id] = l;
          });
          if (resp.items.length === 0) break;
          page++;
        }
        setLitMap(map);
      }
    } catch {
      message.error('加载文件记录失败');
    } finally {
      setFilesLoading(false);
    }
  };

  const statusTagMap: Record<string, { color: string; text: string }> = {
    idle: { color: 'default', text: '空闲' },
    scanning: { color: 'processing', text: '扫描中' },
    error: { color: 'error', text: '错误' },
  };

  const fileStatusTagMap: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '待处理' },
    imported: { color: 'success', text: '已导入' },
    skipped_duplicate: { color: 'warning', text: '重复跳过' },
    failed: { color: 'error', text: '失败' },
  };

  const columns: ColumnsType<MonitoredFolder> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      render: (v: string, r: MonitoredFolder) => (
        <Space>
          <FolderOpenOutlined />
          <span style={{ fontWeight: 500 }}>{v}</span>
        </Space>
      ),
    },
    {
      title: '文件夹路径',
      dataIndex: 'folder_path',
      key: 'folder_path',
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}>
          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => {
        const tag = statusTagMap[v] || { color: 'default', text: v };
        return <Tag color={tag.color}>{tag.text}</Tag>;
      },
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 60,
      render: (v: boolean, r: MonitoredFolder) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggleEnabled(r, checked)} />
      ),
    },
    {
      title: '扫描间隔',
      dataIndex: 'scan_interval_seconds',
      key: 'scan_interval_seconds',
      width: 90,
      render: (v: number) => {
        if (v < 60) return `${v}秒`;
        if (v < 3600) return `${Math.floor(v / 60)}分钟`;
        return `${Math.floor(v / 3600)}小时`;
      },
    },
    {
      title: '自动提取',
      dataIndex: 'auto_extract',
      key: 'auto_extract',
      width: 80,
      render: (v: boolean) => v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>,
    },
    {
      title: '上次扫描',
      dataIndex: 'last_scan_at',
      key: 'last_scan_at',
      width: 140,
      render: (v: string | null) => v ? dayjs(v).format('MM-DD HH:mm:ss') : '-',
    },
    {
      title: '新文件',
      dataIndex: 'last_scan_new_count',
      key: 'last_scan_new_count',
      width: 70,
      render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : <span>0</span>,
    },
    {
      title: '累计导入',
      dataIndex: 'total_imported_count',
      key: 'total_imported_count',
      width: 80,
      render: (v: number) => v > 0 ? <Tag color="green">{v}</Tag> : <span>0</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, r: MonitoredFolder) => (
        <Space size="small">
          <Tooltip title="立即扫描">
            <Button
              size="small"
              icon={<ScanOutlined />}
              loading={scanningIds.has(r.id)}
              onClick={() => handleScan(r.id)}
            />
          </Tooltip>
          <Tooltip title="查看文件记录">
            <Button
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => handleViewFiles(r)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(r)}
            />
          </Tooltip>
          <Popconfirm title="确定删除此监控文件夹？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 错误提示
  const errorFolders = folders.filter(f => f.status === 'error' && f.error_message);

  const fileColumns: ColumnsType<MonitoredFile> = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => {
        const tag = fileStatusTagMap[v] || { color: 'default', text: v };
        return <Tag color={tag.color}>{tag.text}</Tag>;
      },
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 80,
      render: (v: number | null) => {
        if (!v) return '-';
        if (v < 1024) return `${v}B`;
        if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)}KB`;
        return `${(v / 1024 / 1024).toFixed(1)}MB`;
      },
    },
    {
      title: '关联文献',
      dataIndex: 'literature_id',
      key: 'literature_id',
      width: 200,
      ellipsis: true,
      render: (id: string | null) => {
        if (!id) return '-';
        const lit = litMap[id];
        return lit ? (
          <Tooltip title={lit.title}>
            <span style={{ fontSize: 12 }}>{lit.title}</span>
          </Tooltip>
        ) : <span style={{ fontSize: 12, color: '#999' }}>{id.slice(0, 8)}...</span>;
      },
    },
    {
      title: '导入时间',
      dataIndex: 'imported_at',
      key: 'imported_at',
      width: 140,
      render: (v: string | null) => v ? dayjs(v).format('MM-DD HH:mm:ss') : '-',
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      width: 200,
      ellipsis: true,
      render: (v: string | null) => v ? <Tooltip title={v}><span style={{ color: '#ff4d4f', fontSize: 12 }}>{v}</span></Tooltip> : '-',
    },
  ];

  return (
    <>
      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <h2 style={{ margin: 0, fontSize: 18 }}>
              <FolderOpenOutlined style={{ marginRight: 8 }} />
              文件夹监控
            </h2>
          </Space>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchFolders}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加文件夹</Button>
          </Space>
        </div>

        {errorFolders.length > 0 && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={`${errorFolders.length} 个文件夹扫描出错`}
            description={errorFolders.map(f => `${f.name}: ${f.error_message}`).join('；')}
          />
        )}

        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="监控文件夹" value={folders.length} prefix={<FolderOpenOutlined />} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="启用中" value={folders.filter(f => f.enabled).length} valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="累计导入" value={folders.reduce((s, f) => s + f.total_imported_count, 0)} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="扫描中" value={folders.filter(f => f.status === 'scanning').length} valueStyle={{ color: '#1890ff' }} />
            </Card>
          </Col>
        </Row>

        <Table
          rowKey="id"
          columns={columns}
          dataSource={folders}
          loading={loading}
          size="small"
          pagination={false}
          locale={{ emptyText: <Empty description="暂无监控文件夹，点击右上角添加" /> }}
          scroll={{ x: 1200 }}
        />
      </Card>

      {/* 添加/编辑 Modal */}
      <Modal
        title={editingFolder ? '编辑监控文件夹' : '添加监控文件夹'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        width={600}
        okText={editingFolder ? '保存' : '添加'}
        cancelText="取消"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="如：实验室文献文件夹" />
          </Form.Item>

          <Form.Item
            name="folder_path"
            label="文件夹路径"
            rules={[{ required: true, message: '请输入文件夹路径' }]}
            extra="本地笔记本电脑上的文件夹绝对路径，如 E:\文献\新文献"
          >
            <Input placeholder="E:\文献\新文献" />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="scan_interval_seconds"
                label="扫描间隔（秒）"
                rules={[{ required: true, message: '请输入扫描间隔' }]}
                extra="最小30秒，建议300秒（5分钟）"
              >
                <InputNumber min={30} max={86400} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="file_extensions" label="文件扩展名" extra="逗号分隔，留空则全部支持格式">
                <Input placeholder=".pdf,.caj,.epub,.docx,.txt,.html" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="enabled" label="启用监控" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item name="auto_extract" label="自动提取信息" valuePropName="checked" extra="导入后自动触发AI信息提取">
            <Switch />
          </Form.Item>

          <Form.Item name="extraction_model" label="提取模型" extra="留空则使用默认模型">
            <Select
              allowClear
              placeholder="选择模型或留空使用默认"
              options={modelOptions.map(o => ({ label: o.label, value: o.value }))}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="extraction_api_key" label="API Key（可选）">
                <Input.Password placeholder="留空使用默认配置" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="extraction_base_url" label="Base URL（可选）">
                <Input placeholder="留空使用默认配置" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 文件记录 Drawer */}
      <Drawer
        title={
          <Space>
            <FileTextOutlined />
            <span>{drawerFolder?.name} - 文件处理记录</span>
          </Space>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={800}
      >
        {drawerFolder && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`路径：${drawerFolder.folder_path}`}
            />
            <Table
              rowKey="id"
              columns={fileColumns}
              dataSource={files}
              loading={filesLoading}
              size="small"
              pagination={{ pageSize: 20, showSizeChanger: true }}
              locale={{ emptyText: <Empty description="暂无文件记录" /> }}
              scroll={{ x: 800 }}
            />
          </>
        )}
      </Drawer>
    </>
  );
};

export default FolderMonitorPage;
