import React, { useEffect, useState } from 'react';
import { Modal, Spin, Empty, Button, Collapse, Tag, Typography, message, Space } from 'antd';
import { ReloadOutlined, MergeCellsOutlined } from '@ant-design/icons';
import { scanDuplicates, listLiterature } from '../services/literature';
import type { ScanDuplicatesResult, Literature, DuplicateGroup } from '../types';

const { Text, Paragraph } = Typography;

const REASON_LABELS: Record<string, string> = {
  doi: 'DOI相同',
  title: '标题相同',
  'title+authors': '标题+作者相似',
  pdf_hash: '文件哈希相同',
};

const REASON_COLORS: Record<string, string> = {
  doi: 'red',
  title: 'orange',
  'title+authors': 'gold',
  pdf_hash: 'volcano',
};

interface DuplicateScanPanelProps {
  open: boolean;
  onClose: () => void;
  onMerge: (sourceId: string, targetId: string, sourceTitle: string, targetTitle: string) => void;
}

const DuplicateScanPanel: React.FC<DuplicateScanPanelProps> = ({ open, onClose, onMerge }) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanDuplicatesResult | null>(null);
  const [litMap, setLitMap] = useState<Record<string, Literature>>({});

  const doScan = async () => {
    setLoading(true);
    try {
      const scanResult = await scanDuplicates();
      setResult(scanResult);
      // 获取所有涉及的文献信息
      const allIds = new Set<string>();
      scanResult.groups.forEach((g) => {
        g.literature_ids.forEach((id) => allIds.add(id));
      });
      if (allIds.size > 0) {
        // 后端 page_size 上限为 100，需分页获取所有文献
        const map: Record<string, Literature> = {};
        let page = 1;
        let total = Infinity;
        while (Object.keys(map).length < total) {
          const litResult = await listLiterature({ page, page_size: 100 });
          total = litResult.total;
          litResult.items.forEach((l) => { map[l.id] = l; });
          if (litResult.items.length === 0) break;
          page++;
        }
        setLitMap(map);
      }
    } catch (err) {
      console.error('[DuplicateScanPanel] 扫描重复文献失败:', err);
      message.error('扫描失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      doScan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const renderGroup = (group: DuplicateGroup, index: number) => {
    const members = group.literature_ids
      .map((id) => litMap[id])
      .filter((l): l is Literature => l != null);
    const rep = litMap[group.representative_id];

    return (
      <div key={index}>
        <Space wrap style={{ marginBottom: 8 }}>
          {group.match_reasons.map((r) => (
            <Tag key={r} color={REASON_COLORS[r] || 'blue'}>
              {REASON_LABELS[r] || r}
            </Tag>
          ))}
        </Space>
        <div style={{ marginBottom: 8 }}>
          {members.map((l) => (
            <div key={l.id} style={{
              padding: '6px 8px',
              marginBottom: 4,
              background: l.id === group.representative_id ? '#f6ffed' : '#fafafa',
              borderRadius: 4,
              border: l.id === group.representative_id ? '1px solid #b7eb8f' : '1px solid #f0f0f0',
            }}>
              <Space>
                {l.id === group.representative_id && <Tag color="green">推荐保留</Tag>}
                <Text strong>{l.title}</Text>
                {l.pub_year && <Text type="secondary">{l.pub_year}年</Text>}
                {l.doi && <Text type="secondary" style={{ fontSize: 12 }}>DOI: {l.doi}</Text>}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  数据点: {l.extracted_count} | 审核: {l.approved_count}
                </Text>
              </Space>
            </div>
          ))}
        </div>
        <Button
          type="primary"
          size="small"
          icon={<MergeCellsOutlined />}
          onClick={() => {
            // 将非推荐项作为源，推荐项作为目标
            const sourceId = group.literature_ids.find((id) => id !== group.representative_id);
            if (sourceId && rep) {
              const source = litMap[sourceId];
              onMerge(sourceId, group.representative_id, source?.title || sourceId, rep.title);
            }
          }}
        >
          合并此组
        </Button>
      </div>
    );
  };

  return (
    <Modal
      title="重复文献扫描"
      open={open}
      onCancel={onClose}
      width={700}
      footer={[
        <Button key="close" onClick={onClose}>关闭</Button>,
      ]}
    >
      <Spin spinning={loading}>
        {result && (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Text>
                共发现 <Text strong type="danger">{result.total_groups}</Text> 组重复，
                涉及 <Text strong type="danger">{result.total_duplicates}</Text> 条文献
              </Text>
              <Button size="small" icon={<ReloadOutlined />} onClick={doScan}>重新扫描</Button>
            </Space>

            {result.total_groups === 0 ? (
              <Empty description="未发现重复文献" />
            ) : (
              <Collapse
                defaultActiveKey={result.groups.map((_, i) => String(i))}
                items={result.groups.map((g, i) => ({
                  key: String(i),
                  label: (
                    <Space>
                      <Text>第 {i + 1} 组 ({g.literature_ids.length} 条)</Text>
                      {g.match_reasons.map((r) => (
                        <Tag key={r} color={REASON_COLORS[r] || 'blue'}>
                          {REASON_LABELS[r] || r}
                        </Tag>
                      ))}
                    </Space>
                  ),
                  children: renderGroup(g, i),
                }))}
              />
            )}
          </>
        )}
      </Spin>
    </Modal>
  );
};

export default DuplicateScanPanel;
