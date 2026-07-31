import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Table, Button, Input, InputNumber, Space, Modal, Upload, Form, Select, message, Popconfirm, Tag, Tooltip, Progress,
} from 'antd';
import { UploadOutlined, SearchOutlined, DeleteOutlined, ExperimentOutlined, PlusOutlined, RobotOutlined, ReloadOutlined, EyeOutlined, DownloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import DiseaseSelector from '../components/DiseaseSelector';
import StatusBadge from '../components/StatusBadge';
import PdfPreviewModal from '../components/PdfPreviewModal';
import { listLiterature, deleteLiterature, uploadLiterature, triggerExtraction } from '../services/literature';
import { Literature } from '../types';
import { MODEL_OPTIONS, VENDOR_INFO } from '../utils/constants';
import { formatAuthors, truncate } from '../utils/format';
import dayjs from 'dayjs';

const LiteraturePage: React.FC = () => {
  const [items, setItems] = useState<Literature[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [disease, setDisease] = useState('');
  const [province, setProvince] = useState('');
  const [yearStart, setYearStart] = useState<number | undefined>();
  const [yearEnd, setYearEnd] = useState<number | undefined>();
  const [journal, setJournal] = useState('');
  const [sortBy, setSortBy] = useState('created');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [reviewStatus, setReviewStatus] = useState<string>('');  // 审核状态筛选
  const [sortInfo, setSortInfo] = useState<{ field: string | null; order: 'ascend' | 'descend' | null }>({ field: 'created_at', order: 'descend' });
  const [loading, setLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0, fileName: '' });
  const [form] = Form.useForm();
  const navigate = useNavigate();

  // 模型选择提取
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractModel, setExtractModel] = useState<string | undefined>(undefined);
  const [extractLitId, setExtractLitId] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractApiKey, setExtractApiKey] = useState('');
  const [extractBaseUrl, setExtractBaseUrl] = useState('');

  // PDF 预览
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLitId, setPreviewLitId] = useState<string | null>(null);
  const [previewLitTitle, setPreviewLitTitle] = useState('');

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { page, page_size: pageSize };
      if (keyword) params.keyword = keyword;
      if (disease) params.disease = disease;
      if (province) params.province = province;
      if (yearStart) params.year_start = yearStart;
      if (yearEnd) params.year_end = yearEnd;
      if (journal) params.journal = journal;
      if (sortBy) params.sort_by = sortBy;
      if (sortOrder) params.sort_order = sortOrder;
      if (reviewStatus) params.review_status = reviewStatus;
      const resp = await listLiterature(params);
      setItems(resp.items);
      setTotal(resp.total);
    } catch {
      message.error('加载文献列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword, disease, province, yearStart, yearEnd, journal, sortBy, sortOrder, reviewStatus]);

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
    const files: File[] = (values.file || [])
      .map((f: any) => f.originFileObj)
      .filter((f: File | undefined): f is File => !!f);

    if (files.length === 0) { message.error('请选择文件'); return; }

    setUploading(true);
    setBatchProgress({ current: 0, total: files.length, fileName: '' });

    let successCount = 0;
    let failCount = 0;
    const model = values.model;
    const apiKey = values.apiKey || undefined;
    const baseUrl = values.baseUrl || undefined;

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      setBatchProgress({ current: i + 1, total: files.length, fileName: file.name });

      try {
        const fd = new FormData();
        fd.append('file', file);
        // 单文件时使用用户自定义标题，批量时使用文件名
        if (files.length === 1 && values.title) fd.append('title', values.title);
        if (files.length === 1 && values.doi) fd.append('doi', values.doi);
        if (files.length === 1 && values.province) fd.append('province', values.province);

        const resp = await uploadLiterature(fd);

        if (resp?.id) {
          if (model && model !== '') {
            await triggerExtraction(resp.id, { model, apiKey, baseUrl });
          } else {
            await triggerExtraction(resp.id);
          }
        }
        successCount++;
      } catch {
        failCount++;
      }
    }

    setUploading(false);

    if (files.length === 1) {
      if (successCount === 1) {
        message.success('上传成功，已启动 AI 提取');
      } else {
        message.error('上传失败');
      }
    } else {
      const msg = `批量上传完成：成功 ${successCount} 个`;
      if (failCount > 0) {
        message.warning(`${msg}，失败 ${failCount} 个`);
      } else {
        message.success(`${msg}，已全部启动 AI 提取`);
      }
    }

    setUploadOpen(false);
    setBatchProgress({ current: 0, total: 0, fileName: '' });
    form.resetFields();
    fetchList();
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

  const handleTableChange = (pagination: any, _filters: unknown, sorter: any) => {
    // 处理分页变更
    if (pagination.current !== page || pagination.pageSize !== pageSize) {
      setPage(pagination.current);
      setPageSize(pagination.pageSize);
    }
    // 处理排序变更
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    if (s && s.field) {
      const fieldMap: Record<string, string> = {
        title: 'title',
        authors: 'authors',
        journal: 'journal',
        pub_year: 'year',
        province: 'province',
        created_at: 'created',
        extraction_status: 'status',
      };
      const backendField = fieldMap[s.field as string] || (s.field as string);
      const order = s.order as 'ascend' | 'descend' | null;
      const backendOrder = order === 'ascend' ? 'asc' : 'desc';
      setSortInfo({ field: order ? (s.field as string) : null, order });
      setSortBy(order ? backendField : 'created');
      setSortOrder(backendOrder);
    }
  };

  const columns: ColumnsType<Literature> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      sorter: true,
      sortOrder: sortInfo.field === 'title' ? sortInfo.order : null,
      render: (t: string, r: Literature) => (
        <a onClick={() => navigate(`/literature/${r.id}`)}>{truncate(t, 40)}</a>
      ),
    },
    {
      title: '作者',
      dataIndex: 'authors',
      key: 'authors',
      width: 140,
      sorter: true,
      sortOrder: sortInfo.field === 'authors' ? sortInfo.order : null,
      render: (v: string) => formatAuthors(v),
    },
    {
      title: '期刊',
      dataIndex: 'journal',
      key: 'journal',
      width: 140,
      sorter: true,
      sortOrder: sortInfo.field === 'journal' ? sortInfo.order : null,
      render: (v: string) => v || '-',
    },
    {
      title: '年份',
      dataIndex: 'pub_year',
      key: 'year',
      width: 70,
      sorter: true,
      sortOrder: sortInfo.field === 'pub_year' ? sortInfo.order : null,
      render: (v: number | null) => v || '-',
    },
    {
      title: '省份',
      dataIndex: 'province',
      key: 'province',
      width: 80,
      sorter: true,
      sortOrder: sortInfo.field === 'province' ? sortInfo.order : null,
      render: (v: string) => v || '-',
    },
    {
      title: '提取状态',
      dataIndex: 'extraction_status',
      key: 'status',
      width: 90,
      sorter: true,
      sortOrder: sortInfo.field === 'extraction_status' ? sortInfo.order : null,
      render: (s: string) => <StatusBadge status={s} />,
    },
    {
      title: '审核状态',
      key: 'review_status',
      width: 140,
      render: (_: unknown, r: Literature) => {
        const total = r.extracted_count || 0;
        const approved = r.approved_count || 0;
        if (total === 0) {
          return <Tag color="default">无数据</Tag>;
        }
        const percent = Math.round((approved / total) * 100);
        if (approved === total) {
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag color="green">已完成</Tag>
              <span style={{ fontSize: 12 }}>{approved}/{total}</span>
            </div>
          );
        }
        if (approved === 0) {
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag color="red">未审核</Tag>
              <span style={{ fontSize: 12 }}>0/{total}</span>
            </div>
          );
        }
        return (
          <Tooltip title={`${approved} / ${total} 已审核`}>
            <Progress
              percent={percent}
              size="small"
              style={{ width: 100 }}
              strokeColor={percent >= 50 ? '#52c41a' : '#faad14'}
            />
          </Tooltip>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created',
      width: 110,
      sorter: true,
      sortOrder: sortInfo.field === 'created_at' ? sortInfo.order : null,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 270,
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
          <Tooltip title="预览">
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => {
                setPreviewLitId(r.id);
                setPreviewLitTitle(r.title);
                setPreviewOpen(true);
              }}
            />
          </Tooltip>
          <Tooltip title="下载并用本地阅读器打开">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => window.open(`/api/v1/literatures/${r.id}/download`)}
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
            style={{ width: 200 }}
            allowClear
          />
          <DiseaseSelector value={disease} onChange={setDisease} />
          <Input
            placeholder="省份"
            value={province}
            onChange={(e) => setProvince(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 100 }}
            allowClear
          />
          <Input
            placeholder="期刊"
            value={journal}
            onChange={(e) => setJournal(e.target.value)}
            onPressEnter={fetchList}
            style={{ width: 150 }}
            allowClear
          />
          <InputNumber
            placeholder="起始年"
            value={yearStart}
            onChange={(v) => setYearStart(v ?? undefined)}
            style={{ width: 100 }}
            min={1900}
            max={2100}
          />
          <span style={{ padding: '0 4px' }}>~</span>
          <InputNumber
            placeholder="结束年"
            value={yearEnd}
            onChange={(v) => setYearEnd(v ?? undefined)}
            style={{ width: 100 }}
            min={1900}
            max={2100}
          />
          <Select
            value={sortBy}
            onChange={(v) => { setSortBy(v); const fieldMap: Record<string, string | null> = { created: 'created_at', title: 'title', authors: 'authors', year: 'pub_year', journal: 'journal', province: 'province', status: 'extraction_status' }; setSortInfo({ field: fieldMap[v] || 'created_at', order: sortOrder === 'asc' ? 'ascend' : 'descend' }); }}
            style={{ width: 100 }}
            options={[
              { value: 'created', label: '创建时间' },
              { value: 'title', label: '标题' },
              { value: 'authors', label: '作者' },
              { value: 'year', label: '年份' },
              { value: 'journal', label: '期刊' },
              { value: 'province', label: '省份' },
              { value: 'status', label: '状态' },
            ]}
          />
          <Select
            value={sortOrder}
            onChange={(v) => { setSortOrder(v); setSortInfo((prev) => ({ ...prev, order: v === 'asc' ? 'ascend' : 'descend' })); }}
            style={{ width: 80 }}
            options={[
              { value: 'desc', label: '降序' },
              { value: 'asc', label: '升序' },
            ]}
          />
          <Select
            value={reviewStatus}
            onChange={(v) => setReviewStatus(v || '')}
            style={{ width: 100 }}
            placeholder="审核状态"
            allowClear
            options={[
              { value: 'pending', label: '未审核' },
              { value: 'partial', label: '部分审核' },
              { value: 'approved', label: '已完成' },
              { value: 'none', label: '无数据' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => {
            setKeyword(''); setDisease(''); setProvince(''); setYearStart(undefined);
            setYearEnd(undefined); setJournal(''); setSortBy('created'); setSortOrder('desc');
            setReviewStatus(''); setPage(1); setPageSize(20);
            setSortInfo({ field: 'created_at', order: 'descend' });
          }}>重置筛选</Button>
          <Button type="primary" icon={<SearchOutlined />} onClick={fetchList}>查询</Button>
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
          onChange={handleTableChange}
          pagination={{
            current: page,
            total: loading ? items.length : total,
            pageSize,
            pageSizeOptions: [10, 20, 50, 100],
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
          scroll={{ x: 1100 }}
          size="middle"
        />
      </Card>

      <Modal
        title="上传文献"
        open={uploadOpen}
        onCancel={() => { setUploadOpen(false); form.resetFields(); setBatchProgress({ current: 0, total: 0, fileName: '' }); }}
        onOk={handleUpload}
        confirmLoading={uploading}
        okText={uploading ? `上传中 (${batchProgress.current}/${batchProgress.total})` : '上传'}
        okButtonProps={{ disabled: uploading }}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="file" label="文献文件（支持多选）" rules={[{ required: true, message: '请选择文件' }]} valuePropName="fileList" getValueFromEvent={(e: any) => e?.fileList}>
            <Upload beforeUpload={() => false} accept=".pdf,.caj,.epub,.docx,.txt,.html,.htm" maxCount={20} multiple>
              <Button icon={<UploadOutlined />}>选择文献文件（可多选）</Button>
            </Upload>
          </Form.Item>
          <Form.Item name="title" label="标题（选填，批量上传时忽略）">
            <Input placeholder="文献标题" disabled={uploading} />
          </Form.Item>
          <Form.Item name="doi" label="DOI（选填，批量上传时忽略）">
            <Input placeholder="如 10.1038/..." disabled={uploading} />
          </Form.Item>
          <Form.Item name="province" label="省份（选填，批量上传时忽略）">
            <Input placeholder="如 北京" disabled={uploading} />
          </Form.Item>
          <Form.Item name="model" label="AI 提取模型">
            <Select placeholder="默认配置" allowClear options={MODEL_OPTIONS} disabled={uploading} />
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name) return null;
              return (
                <Form.Item name="apiKey" label="API Key（选填）">
                  <Input.Password placeholder={info.apiKeyLabel} disabled={uploading} />
                </Form.Item>
              );
            }}
          </Form.Item>
          <Form.Item noStyle dependencies={['model']}>
            {({ getFieldValue }) => {
              const model = getFieldValue('model');
              const vendor = MODEL_OPTIONS.find((o) => o.value === model)?.vendor || '';
              const info = VENDOR_INFO[vendor];
              if (!vendor || !info.name) return null;
              return (
                <Form.Item name="baseUrl" label="API Base URL（选填）">
                  <Input placeholder={info.baseUrlLabel} defaultValue={info.defaultBaseUrl} disabled={uploading} />
                </Form.Item>
              );
            }}
          </Form.Item>
          {/* 批量上传进度 */}
          {uploading && batchProgress.total > 0 && (
            <div style={{ marginTop: 12 }}>
              <Progress percent={Math.round((batchProgress.current / batchProgress.total) * 100)}
                format={() => `${batchProgress.current}/${batchProgress.total}`} />
              <div style={{ fontSize: 12, color: '#888', marginTop: 4, wordBreak: 'break-all' }}>
                正在处理：{batchProgress.fileName}
              </div>
            </div>
          )}
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

      <PdfPreviewModal
        open={previewOpen}
        literatureId={previewLitId}
        literatureTitle={previewLitTitle}
        onClose={() => setPreviewOpen(false)}
      />
    </>
  );
};

export default LiteraturePage;
