import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Descriptions, Table, Button, Space, Tag, Modal, Input, InputNumber, message, Spin, Select, Row, Col,
} from 'antd';
import { CheckOutlined, CloseOutlined, ExperimentOutlined, ArrowLeftOutlined, RobotOutlined, MenuFoldOutlined, MenuUnfoldOutlined, UpOutlined, DownOutlined, RightOutlined, LeftOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import ConfidenceBadge from '../components/ConfidenceBadge';
import StatusBadge from '../components/StatusBadge';
import {
  getLiterature, getExtractionResults, updateDataPoints, triggerExtraction, updateLiterature,
} from '../services/literature';
import PdfViewer from '../components/PdfViewer';
import { DATA_TYPE_LABEL, MODEL_OPTIONS, VENDOR_INFO } from '../utils/constants';
import dayjs from 'dayjs';

const LiteratureDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [literature, setLiterature] = useState<Literature | null>(null);
  const [dataPoints, setDataPoints] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [reviewNote, setReviewNote] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [modalAction, setModalAction] = useState<'approved' | 'rejected'>('approved');
  const [pollingInterval, setPollingInterval] = useState<number | null>(null);
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractModel, setExtractModel] = useState<string | undefined>(undefined);
  const [extractApiKey, setExtractApiKey] = useState('');
  const [extractBaseUrl, setExtractBaseUrl] = useState('');

  // 面板大小状态
  const [topHeightPercent, setTopHeightPercent] = useState(30);
  const [leftWidthPercent, setLeftWidthPercent] = useState(55);
  const dragRef = useRef<'vertical' | 'horizontal' | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 折叠状态
  const [isTopCollapsed, setIsTopCollapsed] = useState(false);
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false);
  const [isRightCollapsed, setIsRightCollapsed] = useState(true);

  // 编辑状态
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string | number | null>>({});
  const [saving, setSaving] = useState(false);

  // 数据点行内编辑状态
  const [editingRowId, setEditingRowId] = useState<string | null>(null);
  const [editRowData, setEditRowData] = useState<Partial<DataPoint> | null>(null);
  const [editSavingRow, setEditSavingRow] = useState(false);

  const handleStartEdit = () => {
    if (!literature) return;
    setEditForm({
      title: literature.title || '',
      title_en: literature.title_en || '',
      authors: literature.authors || '',
      journal: literature.journal || '',
      pub_year: literature.pub_year ?? null,
      doi: literature.doi || '',
      pmid: literature.pmid || '',
      abstract: literature.abstract || '',
      region: literature.region || '',
      province: literature.province || '',
    });
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditForm({});
  };

  // 数据点行内编辑
  const handleStartEditRow = (record: DataPoint) => {
    setEditingRowId(record.id);
    setEditRowData({ ...record });
  };

  const handleCancelEditRow = () => {
    setEditingRowId(null);
    setEditRowData(null);
  };

  const handleSaveEditRow = async () => {
    if (!id || !editRowData?.id) return;
    setEditSavingRow(true);
    try {
      const payload: Record<string, unknown> = { id: editRowData.id };
      const fields: (keyof DataPoint)[] = [
        'disease', 'province', 'city', 'data_type', 'value', 'unit',
        'sample_size', 'population', 'age_min', 'age_max', 'collection_year',
        'confidence', 'method', 'assay',
      ];
      fields.forEach((f) => {
        if (editRowData[f] !== undefined) {
          payload[f] = editRowData[f];
        }
      });
      await updateDataPoints(id, [payload as any]);
      message.success('数据点已更新');
      setEditingRowId(null);
      setEditRowData(null);
      fetchData();
    } catch {
      message.error('更新失败');
    } finally {
      setEditSavingRow(false);
    }
  };

  const updateEditField = (field: keyof DataPoint, value: unknown) => {
    setEditRowData((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const handleSaveEdit = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const updates: Record<string, unknown> = {};
      Object.entries(editForm).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) {
          updates[k] = k === 'pub_year' ? (v ? Number(v) : null) : v;
        }
      });
      await updateLiterature(id, updates);
      message.success('文献信息已更新');
      setEditing(false);
      fetchData();
    } catch {
      message.error('更新失败');
    } finally {
      setSaving(false);
    }
  };

  const fetchData = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [lit, ext] = await Promise.all([
        getLiterature(id),
        getExtractionResults(id),
      ]);
      setLiterature(lit);
      setDataPoints((ext.data as { data_points?: DataPoint[] })?.data_points || []);
    } catch {
      message.error('加载文献详情失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleExtract = () => {
    setExtractModel(undefined);
    setExtractApiKey('');
    setExtractBaseUrl('');
    setExtractModalOpen(true);
  };

  const confirmExtract = async () => {
    if (!id) return;
    setExtracting(true);
    setExtractModalOpen(false);
    try {
      if (extractModel && extractModel !== '') {
        await triggerExtraction(id, {
          model: extractModel,
          apiKey: extractApiKey || undefined,
          baseUrl: extractBaseUrl || undefined,
        });
      } else {
        await triggerExtraction(id);
      }
      message.success('AI 提取任务已提交，正在轮询进度...');
      const interval = window.setInterval(() => {
        fetchData().then(() => {
          if (literature?.extraction_status !== 'processing') {
            if (pollingInterval) {
              clearInterval(pollingInterval);
              setPollingInterval(null);
            }
            if (literature?.extraction_status === 'done') {
              message.success(`提取完成，共提取 ${literature.extracted_count} 个数据点`);
            } else if (literature?.extraction_status === 'failed') {
              message.error('提取失败，请重试');
            }
          }
        });
      }, 3000);
      setPollingInterval(interval);
    } catch {
      message.error('提取失败');
    } finally {
      setExtracting(false);
    }
  };

  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  const handleSingleReview = async (dpId: string, status: 'approved' | 'rejected') => {
    if (!id) return;
    try {
      await updateDataPoints(id, [{ id: dpId, review_status: status }]);
      message.success(status === 'approved' ? '已通过' : '已驳回');
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const handleBatchReview = async () => {
    if (!id || selectedRowKeys.length === 0) return;
    try {
      const items = selectedRowKeys.map((k) => ({ id: k as string, review_status: modalAction }));
      await updateDataPoints(id, items);
      message.success(`已${modalAction === 'approved' ? '通过' : '驳回'} ${selectedRowKeys.length} 个数据点`);
      setSelectedRowKeys([]);
      setModalOpen(false);
      setReviewNote('');
      fetchData();
    } catch {
      message.error('批量操作失败');
    }
  };

  const openBatchModal = (action: 'approved' | 'rejected') => {
    setModalAction(action);
    setReviewNote('');
    setModalOpen(true);
  };

  const isEditing = (record: DataPoint) => editingRowId === record.id;

  const columns: ColumnsType<DataPoint> = [
    {
      title: '疾病', dataIndex: 'disease', key: 'disease', width: 80,
      sorter: (a, b) => (a.disease || '').localeCompare(b.disease || ''),
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Input size="small" value={editRowData?.disease ?? ''}
            onChange={(e) => updateEditField('disease', e.target.value || null)}
            style={{ width: 70 }} />
        ) : (v || '-'),
    },
    {
      title: '地区', key: 'region', width: 160,
      sorter: (a, b) => {
        const ra = [a.province, a.city].filter(Boolean).join(' ') || '';
        const rb = [b.province, b.city].filter(Boolean).join(' ') || '';
        return ra.localeCompare(rb);
      },
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <Input size="small" value={editRowData?.province ?? ''}
              onChange={(e) => updateEditField('province', e.target.value || null)}
              placeholder="省" style={{ width: 70 }} />
            <Input size="small" value={editRowData?.city ?? ''}
              onChange={(e) => updateEditField('city', e.target.value || null)}
              placeholder="市" style={{ width: 70 }} />
          </Space>
        ) : ([r.province, r.city].filter(Boolean).join(' ') || '-'),
    },
    {
      title: '年龄段', key: 'age', width: 100,
      sorter: (a, b) => {
        const amin = a.age_min ?? Number.MAX_SAFE_INTEGER;
        const bmin = b.age_min ?? Number.MAX_SAFE_INTEGER;
        if (amin !== bmin) return amin - bmin;
        return (a.age_max ?? Number.MAX_SAFE_INTEGER) - (b.age_max ?? Number.MAX_SAFE_INTEGER);
      },
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <InputNumber size="small" value={editRowData?.age_min ?? undefined}
              onChange={(v) => updateEditField('age_min', v ?? null)}
              placeholder="最小" style={{ width: 60 }} min={0} max={150} />
            <InputNumber size="small" value={editRowData?.age_max ?? undefined}
              onChange={(v) => updateEditField('age_max', v ?? null)}
              placeholder="最大" style={{ width: 60 }} min={0} max={150} />
          </Space>
        ) : (
          r.age_min != null && r.age_max != null ? `${r.age_min}-${r.age_max}岁` : '-'
        ),
    },
    {
      title: '数据类型', dataIndex: 'data_type', key: 'dt', width: 100,
      sorter: (a, b) => (a.data_type || '').localeCompare(b.data_type || ''),
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Select size="small" value={editRowData?.data_type ?? undefined}
            onChange={(val) => updateEditField('data_type', val || null)}
            style={{ width: 90 }} allowClear
            options={Object.entries(DATA_TYPE_LABEL).map(([k, label]) => ({ value: k, label }))} />
        ) : (DATA_TYPE_LABEL[v] || v || '-'),
    },
    {
      title: '数值', key: 'value', width: 120,
      sorter: (a, b) => (a.value ?? Number.MAX_SAFE_INTEGER) - (b.value ?? Number.MAX_SAFE_INTEGER),
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size={4}>
            <InputNumber size="small" value={editRowData?.value ?? undefined}
              onChange={(v) => updateEditField('value', v ?? null)}
              style={{ width: 70 }} step={0.1} />
            <Input size="small" value={editRowData?.unit ?? ''}
              onChange={(e) => updateEditField('unit', e.target.value || null)}
              placeholder="单位" style={{ width: 50 }} />
          </Space>
        ) : (
          r.value != null ? `${r.value} ${r.unit || ''}` : '-'
        ),
    },
    {
      title: '样本量', dataIndex: 'sample_size', key: 'ss', width: 80,
      sorter: (a, b) => (a.sample_size ?? Number.MAX_SAFE_INTEGER) - (b.sample_size ?? Number.MAX_SAFE_INTEGER),
      render: (v: number, r: DataPoint) =>
        isEditing(r) ? (
          <InputNumber size="small" value={editRowData?.sample_size ?? undefined}
            onChange={(val) => updateEditField('sample_size', val ?? null)}
            style={{ width: 70 }} min={0} />
        ) : (v || '-'),
    },
    {
      title: '采集年份', dataIndex: 'collection_year', key: 'cy', width: 80,
      sorter: (a, b) => (a.collection_year ?? Number.MAX_SAFE_INTEGER) - (b.collection_year ?? Number.MAX_SAFE_INTEGER),
      render: (v: number, r: DataPoint) =>
        isEditing(r) ? (
          <InputNumber size="small" value={editRowData?.collection_year ?? undefined}
            onChange={(val) => updateEditField('collection_year', val ?? null)}
            style={{ width: 70 }} min={1900} max={2100} />
        ) : (v || '-'),
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'cf', width: 80,
      sorter: (a, b) => {
        const order = { high: 3, medium: 2, low: 1 };
        return (order[a.confidence as keyof typeof order] || 0) - (order[b.confidence as keyof typeof order] || 0);
      },
      render: (v: string, r: DataPoint) =>
        isEditing(r) ? (
          <Select size="small" value={editRowData?.confidence ?? undefined}
            onChange={(val) => updateEditField('confidence', val || null)}
            style={{ width: 70 }} allowClear
            options={[
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]} />
        ) : (<ConfidenceBadge confidence={v} />),
    },
    {
      title: '状态', key: 'status', width: 80,
      sorter: (a, b) => {
        const order: Record<string, number> = { approved: 3, pending: 2, rejected: 1 };
        return (order[a.review_status] || 0) - (order[b.review_status] || 0);
      },
      render: (_: unknown, r: DataPoint) => (
        <Tag color={r.review_status === 'approved' ? 'green' : r.review_status === 'rejected' ? 'red' : 'default'}>
          {r.review_status === 'approved' ? '已通过' : r.review_status === 'rejected' ? '已驳回' : '待审核'}
        </Tag>
      ),
    },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: DataPoint) =>
        isEditing(r) ? (
          <Space size="small">
            <Button size="small" type="primary" icon={<SaveOutlined />} loading={editSavingRow} onClick={handleSaveEditRow}>保存</Button>
            <Button size="small" onClick={handleCancelEditRow}>取消</Button>
          </Space>
        ) : (
          <Space size="small">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleStartEditRow(r)}>编辑</Button>
            <Button size="small" type="primary" icon={<CheckOutlined />}
              disabled={r.review_status === 'approved'}
              onClick={() => handleSingleReview(r.id, 'approved')} />
            <Button size="small" danger icon={<CloseOutlined />}
              disabled={r.review_status === 'rejected'}
              onClick={() => handleSingleReview(r.id, 'rejected')} />
          </Space>
        ),
    },
  ];

  // 拖拽调整面板大小
  const handleDragStart = useCallback((direction: 'vertical' | 'horizontal') => (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = direction;
    document.body.style.cursor = direction === 'vertical' ? 'row-resize' : 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();

      if (dragRef.current === 'vertical') {
        const ratio = ((e.clientY - rect.top) / rect.height) * 100;
        setTopHeightPercent(Math.min(65, Math.max(15, ratio)));
      } else {
        const ratio = ((e.clientX - rect.left) / rect.width) * 100;
        setLeftWidthPercent(Math.min(80, Math.max(25, ratio)));
      }
    };

    const handleMouseUp = () => {
      if (dragRef.current) {
        dragRef.current = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;

  return (
    <>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/literature')} style={{ marginBottom: 12 }}>
        返回列表
      </Button>

      {/* 可拖拽调整的整体容器 */}
      <div
        ref={containerRef}
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - 90px)',
          minHeight: 500,
        }}
      >
        {/* ===== 上方：文献信息卡片 ===== */}
        {isTopCollapsed ? (
          /* 折叠态：仅显示标题栏 */
          <div
            style={{
              flexShrink: 0,
              background: '#fff',
              border: '1px solid #e8e8e8',
              borderRadius: 6,
              padding: '6px 16px',
              marginBottom: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              cursor: 'pointer',
            }}
            onClick={() => setIsTopCollapsed(false)}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>文献详情</span>
            <DownOutlined style={{ color: '#888' }} />
          </div>
        ) : (
          <>
            <div style={{ flex: `0 0 ${topHeightPercent}%`, overflow: 'auto', minHeight: 0, marginBottom: 0, transition: 'flex 0.25s' }}>
              <Card
                style={{ height: '100%' }}
                styles={{ body: { height: '100%', overflow: 'auto' } }}
                title={
                  <Space>
                    <span style={{ cursor: 'pointer' }} onClick={() => setIsTopCollapsed(true)}>
                      <UpOutlined style={{ marginRight: 4, color: '#888' }} />
                    </span>
                    {editing ? '编辑文献信息' : (literature?.title || '文献详情')}
                  </Space>
                }
                extra={
                  editing ? (
                    <Space>
                      <Button size="small" onClick={handleCancelEdit}>取消</Button>
                      <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSaveEdit}>保存</Button>
                    </Space>
                  ) : (
                    <Button size="small" icon={<EditOutlined />} onClick={handleStartEdit}>编辑</Button>
                  )
                }
              >
                {editing ? (
                  <Row gutter={[16, 12]}>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>标题</div>
                      <Input value={String(editForm.title ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>英文标题</div>
                      <Input value={String(editForm.title_en ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, title_en: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>作者</div>
                      <Input value={String(editForm.authors ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, authors: e.target.value }))} />
                    </Col>
                    <Col span={12}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>期刊</div>
                      <Input value={String(editForm.journal ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, journal: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>年份</div>
                      <Input value={editForm.pub_year != null ? String(editForm.pub_year) : ''} onChange={(e) => setEditForm((f) => ({ ...f, pub_year: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>DOI</div>
                      <Input value={String(editForm.doi ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, doi: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>PMID</div>
                      <Input value={String(editForm.pmid ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, pmid: e.target.value }))} />
                    </Col>
                    <Col span={6}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>省份</div>
                      <Input value={String(editForm.province ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, province: e.target.value }))} />
                    </Col>
                    <Col span={24}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: '#888' }}>摘要</div>
                      <Input.TextArea rows={3} value={String(editForm.abstract ?? '')} onChange={(e) => setEditForm((f) => ({ ...f, abstract: e.target.value }))} />
                    </Col>
                  </Row>
                ) : (
                  <>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="作者">{literature?.authors || '-'}</Descriptions.Item>
                      <Descriptions.Item label="期刊">{literature?.journal || '-'}</Descriptions.Item>
                      <Descriptions.Item label="年份">{literature?.pub_year || '-'}</Descriptions.Item>
                      <Descriptions.Item label="DOI">{literature?.doi || '-'}</Descriptions.Item>
                      <Descriptions.Item label="省份">{literature?.province || '-'}</Descriptions.Item>
                      <Descriptions.Item label="提取状态">
                        <StatusBadge status={literature?.extraction_status || 'pending'} />
                      </Descriptions.Item>
                      <Descriptions.Item label="审核进度">
                        {literature?.approved_count || 0} / {literature?.extracted_count || 0} 已通过
                      </Descriptions.Item>
                    </Descriptions>
                    {literature?.abstract && (
                      <p style={{ color: '#666', marginTop: 12 }}>{literature.abstract}</p>
                    )}
                    <Space style={{ marginTop: 12 }}>
                      <Button icon={<ExperimentOutlined />} onClick={handleExtract} loading={extracting}>
                        AI 提取
                      </Button>
                    </Space>
                  </>
                )}
              </Card>
            </div>

            {/* 水平拖拽手柄 */}
            <div
              onMouseDown={handleDragStart('vertical')}
              style={{
                height: 6,
                cursor: 'row-resize',
                background: 'linear-gradient(to bottom, #d9d9d9, #bfbfbf, #d9d9d9)',
                flexShrink: 0,
                borderRadius: '0 0 2px 2px',
                margin: '0 0',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#1677ff'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'linear-gradient(to bottom, #d9d9d9, #bfbfbf, #d9d9d9)'; }}
            />
          </>
        )}

        {/* ===== 下方：数据点 + PDF 预览 分栏 ===== */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* 左侧：数据点表格 */}
          {isLeftCollapsed ? (
            /* 折叠态：左侧竖条，内容向左贴边 */
            <div
              style={{
                flexShrink: 0,
                width: 32,
                background: '#fafafa',
                border: '1px solid #e8e8e8',
                borderLeft: 'none',
                borderRadius: '0 6px 6px 0',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                gap: 8,
              }}
              onClick={() => setIsLeftCollapsed(false)}
              title="展开数据点面板"
            >
              <RightOutlined style={{ fontSize: 12, color: '#888' }} />
              <span
                style={{
                  writingMode: 'vertical-rl',
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#666',
                  letterSpacing: 2,
                }}
              >
                数据点
              </span>
            </div>
          ) : (
            <>
              <div style={{ flex: isRightCollapsed ? '1 1 0%' : `0 0 ${leftWidthPercent}%`, minWidth: 0, display: 'flex', flexDirection: 'column', transition: 'flex 0.25s' }}>
                <Card
                  title={
                    <Space>
                      <MenuFoldOutlined
                        style={{ cursor: 'pointer', color: '#888' }}
                        onClick={() => setIsLeftCollapsed(true)}
                      />
                      <span>{`数据点（${dataPoints.length}）`}</span>
                    </Space>
                  }
                  extra={
                    <Space>
                      <Button
                        type="primary"
                        icon={<CheckOutlined />}
                        disabled={selectedRowKeys.length === 0}
                        onClick={() => openBatchModal('approved')}
                      >
                        批量通过
                      </Button>
                      <Button
                        danger
                        icon={<CloseOutlined />}
                        disabled={selectedRowKeys.length === 0}
                        onClick={() => openBatchModal('rejected')}
                      >
                        批量驳回
                      </Button>
                    </Space>
                  }
                  styles={{ body: { flex: 1, overflow: 'auto', padding: 0 } }}
                  style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
                >
                  <Table
                    rowKey="id"
                    dataSource={dataPoints}
                    columns={columns}
                    showSorterTooltip={{ title: '点击排序' }}
                    scroll={{ x: 1400 }}
                    size="middle"
                    rowSelection={{
                      selectedRowKeys,
                      onChange: (keys) => setSelectedRowKeys(keys),
                      getCheckboxProps: (r: DataPoint) => ({
                        disabled: r.review_status !== 'pending' || isEditing(r),
                      }),
                    }}
                    pagination={false}
                  />
                </Card>
              </div>

              {/* 垂直拖拽手柄（仅当右侧未折叠时显示） */}
              {!isRightCollapsed && (
                <div
                  onMouseDown={handleDragStart('horizontal')}
                  style={{
                    width: 6,
                    cursor: 'col-resize',
                    background: 'linear-gradient(to right, #d9d9d9, #bfbfbf, #d9d9d9)',
                    flexShrink: 0,
                    margin: '0 2px',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#1677ff'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'linear-gradient(to right, #d9d9d9, #bfbfbf, #d9d9d9)'; }}
                />
              )}
            </>
          )}

          {/* 右侧：PDF 预览 */}
          {isRightCollapsed ? (
            /* 折叠态：右侧竖条，内容向右贴边 */
            <div
              style={{
                flexShrink: 0,
                width: 32,
                background: '#fafafa',
                border: '1px solid #e8e8e8',
                borderRight: 'none',
                borderRadius: '6px 0 0 6px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                gap: 8,
              }}
              onClick={() => setIsRightCollapsed(false)}
              title="展开文献预览面板"
            >
              <LeftOutlined style={{ fontSize: 12, color: '#888' }} />
              <span
                style={{
                  writingMode: 'vertical-rl',
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#666',
                  letterSpacing: 2,
                }}
              >
                文献预览
              </span>
            </div>
          ) : (
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', transition: 'flex 0.25s' }}>
              <Card
                title={
                  <Space>
                    <MenuFoldOutlined
                      style={{ cursor: 'pointer', color: '#888' }}
                      onClick={() => setIsRightCollapsed(true)}
                    />
                    <span>文献预览</span>
                  </Space>
                }
                styles={{ body: { padding: 8, flex: 1, overflow: 'auto' } }}
                style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
              >
                {id ? (
                  <PdfViewer
                    literatureId={id}
                    defaultScale={0.8}
                    maxHeight="100%"
                  />
                ) : (
                  <div style={{ textAlign: 'center', paddingTop: 100, color: '#999' }}>
                    无法加载预览
                  </div>
                )}
              </Card>
            </div>
          )}
        </div>
      </div>

      <Modal
        title={modalAction === 'approved' ? '批量审核通过' : '批量驳回'}
        open={modalOpen}
        onOk={handleBatchReview}
        onCancel={() => { setModalOpen(false); setReviewNote(''); }}
        okText="确认"
        cancelText="取消"
      >
        <p style={{ marginBottom: 12 }}>
          将对选中的 {selectedRowKeys.length} 个数据点{modalAction === 'approved' ? '通过' : '驳回'}审核。
        </p>
        <Input.TextArea
          placeholder="审核备注（选填）"
          value={reviewNote}
          onChange={(e) => setReviewNote(e.target.value)}
          rows={3}
        />
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

export default LiteratureDetail;
