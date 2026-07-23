import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Table, Button, Input, Space, Modal, Upload, Form, Select, message, Popconfirm, Tag, Tooltip,
} from 'antd';
import { UploadOutlined, SearchOutlined, DeleteOutlined, ExperimentOutlined, PlusOutlined, RobotOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import DiseaseSelector from '../components/DiseaseSelector';
import StatusBadge from '../components/StatusBadge';
import { listLiterature, deleteLiterature, uploadLiterature, triggerExtraction } from '../services/literature';
import { Literature } from '../types';
import { MODEL_OPTIONS, VENDOR_INFO } from '../utils/constants';
import { formatAuthors, truncate } from '../utils/format';
import dayjs from 'dayjs';

const LiteraturePage: React.FC = () => {
  const [items, setItems] = useState<Literature[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState('');
  const [disease, setDisease] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  // 模型选择提取
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractModel, setExtractModel] = useState<string | undefined>(undefined);
  const [extractLitId, setExtractLitId] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractApiKey, setExtractApiKey] = useState('');
  const [extractBaseUrl, setExtractBaseUrl] = useState('');

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page, page_size: 20 };
      if (keyword) params.keyword = keyword;
      if (disease) params.disease = disease;
      const resp = await listLiterature(params);
      setItems(resp.items);
      setTotal(resp.total);
    } catch {
      message.error('加载文献列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, keyword, disease]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleDelete = async (id: string) => {
    try {
      await deleteLiterature(id);
      message.success('删除成功');
      fetchList();
    } catch {
      message.error('删除失败');
    }
  };

  const handleUpload = async () => {
    const values = await form.validateFields();
    setUploading(true);
    try {
      const fd = new FormData();
      const file = values.file?.[0]?.originFileObj;
      if (!file) { message.error('请选择文件'); return; }
      fd.append('file', file);
      if (values.title) fd.append('title', values.title);
      if (values.doi) fd.append('doi', values.doi);
      if (values.province) fd.append('province', values.province);

      const resp = await uploadLiterature(fd);
      message.success('上传成功');
      setUploadOpen(false);
      form.resetFields();

      if (resp.data?.id) {
        if (values.model !== undefined && values.model !== '') {
          await triggerExtraction(resp.data.id, {
            model: values.model,
            apiKey: values.apiKey || undefined,
            baseUrl: values.baseUrl || undefined,
          });
          message.success(`已使用 ${MODEL_OPTIONS.find((o) => o.value === values.model)?.label || '默认配置'} 启动 AI 提取`);
        } else {
          await triggerExtraction(resp.data.id);
          message.success('已使用默认配置启动 AI 提取');
        }
      }
      fetchList();
    } catch {
      message.error('上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleExtract = (id: string) => {
    setExtractLitId(id);
    setExtractModel(undefined);
    setExtractApiKey('');
    setExtractBaseUrl('');
    setExtractModalOpen(true);
  };

  const confirmExtract = async () => {
    if (!extractLitId) return;
    setExtracting(true);
    try {
      if (extractModel && extractModel !== '') {
        await triggerExtraction(extractLitId, {
          model: extractModel,
          apiKey: extractApiKey || undefined,
          baseUrl: extractBaseUrl || undefined,
        });
      } else {
        await triggerExtraction(extractLitId);
      }
      message.success(`已使用 ${MODEL_OPTIONS.find((o) => o.value === extractModel)?.label || '默认模型'} 启动 AI 提取`);
      setExtractModalOpen(false);
      fetchList();
    } catch {
      message.error('提取失败，请检查后端服务是否正常');
    } finally {
      setExtracting(false);
    }
  };

  const columns: ColumnsType<Literature> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      render: (t: string, r: Literature) => (
        <a onClick={() => navigate(`/literature/${r.id}`)}>{truncate(t, 40)}</a>
      ),
    },
    {
      title: '作者',
      dataIndex: 'authors',
      key: 'authors',
      width: 140,
      render: (v: string) => formatAuthors(v),
    },
    {
      title: '期刊',
      dataIndex: 'journal',
      key: 'journal',
      width: 140,
      render: (v: string) => v || '-',
    },
    {
      title: '年份',
      dataIndex: 'pub_year',
      key: 'year',
      width: 70,
      render: (v: number | null) => v || '-',
    },
    {
      title: '省份',
      dataIndex: 'province',
      key: 'province',
      width: 80,
      render: (v: string) => v || '-',
    },
    {
      title: '提取状态',
      dataIndex: 'extraction_status',
      key: 'status',
      width: 90,
      render: (s: string) => <StatusBadge status={s} />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created',
      width: 110,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, r: Literature) => (
        <Space size="small">
          <Tooltip title="AI 提取">
            <Button
              size="small"
              icon={<ExperimentOutlined />}
              onClick={() => handleExtract(r.id)}
              loading={r.extraction_status === 'processing'}
              disabled={r.extraction_status === 'processing'}
            />
          </Tooltip>
          <Button size="small" onClick={() => navigate(`/literature/${r.id}`)}>详情</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="搜索标题/作者/期刊"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 260 }}
            allowClear
          />
          <DiseaseSelector value={disease} onChange={setDisease} />
          <Button icon={<ReloadOutlined />} onClick={() => { setKeyword(''); setDisease(''); setPage(1); }}>重置筛选</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
            上传文献
          </Button>
        </Space>
      </Card>

      <Card>
        <Table
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            onChange: (p) => setPage(p),
            showTotal: (t) => `共 ${t} 条`,
          }}
          scroll={{ x: 1100 }}
          size="middle"
        />
      </Card>

      <Modal
        title="上传文献"
        open={uploadOpen}
        onCancel={() => { setUploadOpen(false); form.resetFields(); }}
        onOk={handleUpload}
        confirmLoading={uploading}
        okText="上传"
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="file" label="PDF 文件" rules={[{ required: true, message: '请选择文件' }]} valuePropName="fileList" getValueFromEvent={(e: any) => e?.fileList}>
            <Upload beforeUpload={() => false} accept=".pdf" maxCount={1}>
              <Button icon={<UploadOutlined />}>选择 PDF 文件</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="title" label="标题（选填）">
            <Input placeholder="文献标题" />
          </Form.Item>
          <Form.Item name="doi" label="DOI（选填）">
            <Input placeholder="如 10.1038/..." />
          </Form.Item>
          <Form.Item name="province" label="省份（选填）">
            <Input placeholder="如 北京" />
          </Form.Item>
          <Form.Item name="model" label="AI 提取模型">
            <Select placeholder="默认配置" allowClear options={MODEL_OPTIONS} />
          </Form.Item>
          <Form.Item name="apiKey" label="API Key（选填）" noStyle>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name) return null;
              return (
                <Input.Password placeholder={info.apiKeyLabel} style={{ marginBottom: 8 }} />
              );
            }}
          </Form.Item>
          <Form.Item name="baseUrl" label="API Base URL（选填）" noStyle>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name) return null;
              return (
                <Input placeholder={info.baseUrlLabel} defaultValue={info.defaultBaseUrl} />
              );
            }}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={<><RobotOutlined /> 选择提取模型</>}
        open={extractModalOpen}
        onCancel={() => setExtractModalOpen(false)}
        onOk={confirmExtract}
        confirmLoading={extracting}
        okText="开始提取"
        width={520}
      >
        <p style={{ marginBottom: 16, color: '#888' }}>选择用于 AI 数据提取的大语言模型。不同模型的提取精度和速度可能有所差异。</p>
        <Select
          placeholder="默认模型"
          allowClear
          style={{ width: '100%', marginBottom: 16 }}
          value={extractModel}
          onChange={(v) => {
            setExtractModel(v);
            const vendor = MODEL_OPTIONS.find((o) => o.value === v)?.vendor || '';
            setExtractBaseUrl(VENDOR_INFO[vendor]?.defaultBaseUrl || '');
          }}
          options={MODEL_OPTIONS}
        />
        {extractModel && extractModel !== '' && (() => {
          const vendor = MODEL_OPTIONS.find((o) => o.value === extractModel)?.vendor || '';
          const info = VENDOR_INFO[vendor];
          if (!vendor || !info.name) return null;
          return (
            <>
              <Input.Password
                placeholder={info.apiKeyLabel}
                value={extractApiKey}
                onChange={(e) => setExtractApiKey(e.target.value)}
                style={{ marginBottom: 12 }}
              />
              <Input
                placeholder={info.baseUrlLabel}
                value={extractBaseUrl}
                onChange={(e) => setExtractBaseUrl(e.target.value)}
              />
            </>
          );
        })()}
      </Modal>
    </>
  );
};

export default LiteraturePage;
