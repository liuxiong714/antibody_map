import React, { useEffect, useState } from 'react';
import { Card, Table, Empty, Divider } from 'antd';
import { getPathogenMonitoringByLiterature, type PathogenMonitoringItem } from '../services/epidemic';

// 文献详情页：只读展示该文献的病原学监测记录（阶段2提取、阶段3展示）
const PathogenPanel: React.FC<{ literatureId: string }> = ({ literatureId }) => {
  const [items, setItems] = useState<PathogenMonitoringItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!literatureId) return;
    let cancelled = false;
    setLoading(true);
    getPathogenMonitoringByLiterature(literatureId)
      .then((r) => { if (!cancelled) setItems(r.items || []); })
      .catch(() => { if (!cancelled) setItems([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [literatureId]);

  const columns = [
    { title: '病原体', dataIndex: 'pathogen_name', width: 130 },
    { title: '类型', dataIndex: 'pathogen_type', width: 70 },
    { title: '基因型', dataIndex: 'genotype', width: 80 },
    { title: '血清型', dataIndex: 'serotype', width: 80 },
    { title: '亚型', dataIndex: 'subtype', width: 90 },
    { title: '谱系/流行株', dataIndex: 'lineage', width: 120 },
    { title: '检出率', dataIndex: 'detection_rate', width: 80, render: (v: number | null) => v == null ? '-' : `${v}%` },
    { title: '样本量', dataIndex: 'sample_size', width: 70 },
    { title: '省份', dataIndex: 'province', width: 70 },
    { title: '城市', dataIndex: 'city', width: 70 },
    { title: '年份', dataIndex: 'collection_year', width: 60 },
    { title: '检测方法', dataIndex: 'detection_method', ellipsis: true },
    { title: '来源', dataIndex: 'source_context', ellipsis: true },
  ];

  return (
    <Card
      size="small"
      title="病原学监测"
      style={{ marginBottom: 8 }}
      styles={{ body: { padding: 0 } }}
    >
      {loading ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="加载中..." />
      ) : items.length === 0 ? (
        <div style={{ padding: 16 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该文献暂无病原学监测数据" /></div>
      ) : (
        <>
          <Divider orientation="left" plain style={{ margin: '12px 0 8px' }}>记录（{items.length}）</Divider>
          <Table<PathogenMonitoringItem>
            rowKey="id"
            dataSource={items}
            columns={columns}
            size="small"
            pagination={false}
            scroll={{ x: 1100 }}
          />
        </>
      )}
    </Card>
  );
};

export default PathogenPanel;