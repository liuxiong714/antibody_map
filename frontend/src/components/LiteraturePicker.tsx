import React, { useEffect, useState } from 'react';
import {
  Modal, Table, Input, Select, Space, Tag, Typography, Spin, Empty, Button, Alert,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { listLiterature } from '../services/literature';
import type { Literature } from '../types';

const { Text } = Typography;

/** 常见省份（可按需增补），用于文献列表筛选。 */
const PROVINCES = [
  '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
  '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东',
  '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾',
  '内蒙古', '广西', '西藏', '宁夏', '新疆',
];

/** 提取状态友好显示 */
const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  done: { text: '已提取', color: 'success' },
  done_no_data: { text: '已完成(无数据)', color: 'default' },
  failed: { text: '失败', color: 'error' },
  processing: { text: '提取中', color: 'processing' },
  queued: { text: '排队中', color: 'warning' },
  pending: { text: '未提取', color: 'default' },
};

interface Props {
  open: boolean;
  onClose: () => void;
  /** 用户确认需要定向抽取的文献 ID 列表 */
  onConfirm: (ids: string[]) => void;
}

/**
 * 文献选择器：在文献列表（/literatures 接口）中按 省份/关键词 筛选，
 * 跨页勾选多篇文献，供知识图谱「定向抽取」使用。
 */
export default function LiteraturePicker({ open, onClose, onConfirm }: Props) {
  const [items, setItems] = useState<Literature[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [province, setProvince] = useState<string | undefined>(undefined);
  const [keyword, setKeyword] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [kgFilter, setKgFilter] = useState<boolean | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  // 打开/筛选/分页变化时加载文献列表
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    (async () => {
      try {
        const params: Record<string, unknown> = { page, page_size: pageSize };
        if (province) params.province = province;
        if (keyword.trim()) params.keyword = keyword.trim();
        if (kgFilter !== undefined) params.kg_extracted = kgFilter;
        const res = await listLiterature(params, { signal: controller.signal });
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      } catch {
        if (!cancelled) { setItems([]); setTotal(0); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [open, page, pageSize, province, keyword, kgFilter]);

  const resetFilters = () => {
    setPage(1);
    setKeyword('');
    setSearchInput('');
    setProvince(undefined);
    setKgFilter(undefined);
  };

  const handleConfirm = () => {
    onConfirm(selectedRowKeys);
    setSelectedRowKeys([]);
    onClose();
  };

  const handleCancel = () => {
    setSelectedRowKeys([]);
    onClose();
  };

  const columns: ColumnsType<Literature> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (_: unknown, r: Literature) => (
        <Space direction="vertical" size={0}>
          <Text ellipsis style={{ maxWidth: 380 }}>{r.title || '(无标题)'}</Text>
          <Space size={4} wrap>
            {r.province && <Tag color="green">{r.province}</Tag>}
            {r.pub_year && <Tag>{r.pub_year}</Tag>}
            {r.file_format && <Tag color="geekblue">{r.file_format}</Tag>}
          </Space>
        </Space>
      ),
    },
    {
      title: '提取状态',
      dataIndex: 'extraction_status',
      key: 'extraction_status',
      width: 140,
      render: (v: string) => {
        const meta = STATUS_LABEL[v] || { text: v, color: 'default' };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: 'KG抽取',
      dataIndex: 'kg_extracted',
      key: 'kg_extracted',
      width: 90,
      render: (v: boolean, r: Literature) => (
        v ? (
          <Tag color="purple">已抽取 {r.kg_triple_count ?? ''}</Tag>
        ) : (
          <Tag>未抽取</Tag>
        )
      ),
    },
  ];

  return (
    <Modal
      open={open}
      title="从文献列表选择"
      width={780}
      onCancel={handleCancel}
      footer={[
        <Button key="cancel" onClick={handleCancel}>取消</Button>,
        <Button key="ok" type="primary" disabled={selectedRowKeys.length === 0} onClick={handleConfirm}>
          使用所选（{selectedRowKeys.length} 篇）
        </Button>,
      ]}
    >
      <Alert
        style={{ marginBottom: 12 }}
        type="info"
        showIcon
        message="勾选需要定向抽取的文献（可跨页累计）。抽取具有幂等性，已在知识库中抽取过的文献会被自动跳过。"
      />
      <Space style={{ width: '100%', marginBottom: 12 }} align="center">
        <Select
          style={{ width: 140 }}
          placeholder="按省份筛选"
          allowClear
          value={province}
          onChange={setProvince}
          options={PROVINCES.map((p) => ({ value: p, label: p }))}
        />
        <Select
          style={{ width: 140 }}
          placeholder="KG抽取状态"
          allowClear
          value={kgFilter}
          onChange={setKgFilter}
          options={[
            { value: true, label: '已抽取' },
            { value: false, label: '未抽取' },
          ]}
        />
        <Input.Search
          style={{ width: 280 }}
          placeholder="按标题/作者/期刊关键词搜索"
          allowClear
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onSearch={(v) => { setPage(1); setKeyword(v.trim()); }}
        />
        <Button icon={<ReloadOutlined />} onClick={resetFilters}>重置</Button>
      </Space>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无匹配文献" />
        ) : (
          <Table<Literature>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={items}
            rowSelection={{
              selectedRowKeys,
              onChange: (keys) => setSelectedRowKeys(keys as string[]),
              preserveSelectedRowKeys: true,
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50],
              onChange: (p, ps) => { setPage(p); setPageSize(ps); },
            }}
            scroll={{ y: 360 }}
          />
        )}
      </Spin>
      {selectedRowKeys.length > 0 && (
        <Text style={{ marginTop: 8 }} type="secondary">
          已勾选 {selectedRowKeys.length} 篇（跨页累计）
        </Text>
      )}
    </Modal>
  );
}