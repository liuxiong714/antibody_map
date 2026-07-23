import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Descriptions, Table, Button, Space, Tag, Modal, Input, message, Spin, Row, Col, Popconfirm,
} from 'antd';
import { CheckOutlined, CloseOutlined, ExperimentOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import ConfidenceBadge from '../components/ConfidenceBadge';
import StatusBadge from '../components/StatusBadge';
import {
  getLiterature, getExtractionResults, updateDataPoints, triggerExtraction,
} from '../services/literature';
import { Literature, DataPoint, ExtractionStatus } from '../types';
import { DATA_TYPE_LABEL } from '../utils/constants';
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

  const handleExtract = async () => {
    if (!id) return;
    setExtracting(true);
    try {
      await triggerExtraction(id);
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

  const columns: ColumnsType<DataPoint> = [
    {
      title: '疾病', dataIndex: 'disease', key: 'disease', width: 80,
      sorter: (a, b) => (a.disease || '').localeCompare(b.disease || ''),
    },
    {
      title: '地区', key: 'region', width: 160,
      sorter: (a, b) => {
        const ra = [a.province, a.city].filter(Boolean).join(' ') || '';
        const rb = [b.province, b.city].filter(Boolean).join(' ') || '';
        return ra.localeCompare(rb);
      },
      render: (_: unknown, r: DataPoint) => [r.province, r.city].filter(Boolean).join(' ') || '-',
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
        r.age_min != null && r.age_max != null ? `${r.age_min}-${r.age_max}岁` : '-',
    },
    {
      title: '数据类型', dataIndex: 'data_type', key: 'dt', width: 100,
      sorter: (a, b) => (a.data_type || '').localeCompare(b.data_type || ''),
      render: (v: string) => DATA_TYPE_LABEL[v] || v,
    },
    {
      title: '数值', key: 'value', width: 120,
      sorter: (a, b) => (a.value ?? Number.MAX_SAFE_INTEGER) - (b.value ?? Number.MAX_SAFE_INTEGER),
      render: (_: unknown, r: DataPoint) =>
        r.value != null ? `${r.value} ${r.unit || ''}` : '-',
    },
    {
      title: '样本量', dataIndex: 'sample_size', key: 'ss', width: 80,
      sorter: (a, b) => (a.sample_size ?? Number.MAX_SAFE_INTEGER) - (b.sample_size ?? Number.MAX_SAFE_INTEGER),
    },
    {
      title: '采集年份', dataIndex: 'collection_year', key: 'cy', width: 80,
      sorter: (a, b) => (a.collection_year ?? Number.MAX_SAFE_INTEGER) - (b.collection_year ?? Number.MAX_SAFE_INTEGER),
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'cf', width: 80,
      sorter: (a, b) => {
        const order = { high: 3, medium: 2, low: 1 };
        return (order[a.confidence as keyof typeof order] || 0) - (order[b.confidence as keyof typeof order] || 0);
      },
      render: (v: string) => <ConfidenceBadge confidence={v} />,
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
      render: (_: unknown, r: DataPoint) => (
        <Space size="small">
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

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;

  return (
    <>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/literature')} style={{ marginBottom: 16 }}>
        返回列表
      </Button>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title={literature?.title || '文献详情'} column={2} size="small">
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
      </Card>

      <Card
        title={`数据点（${dataPoints.length}）`}
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
      >
        <Table
          rowKey="id"
          dataSource={dataPoints}
          columns={columns}
          showSorterTooltip={{ title: '点击排序' }}
          scroll={{ x: 1100 }}
          size="middle"
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
            getCheckboxProps: (r: DataPoint) => ({
              disabled: r.review_status !== 'pending',
            }),
          }}
          pagination={false}
        />
      </Card>

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
    </>
  );
};

export default LiteratureDetail;
