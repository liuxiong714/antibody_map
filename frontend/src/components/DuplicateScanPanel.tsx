import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Modal, Spin, Empty, Button, Collapse, Tag, Typography, message, Space, Popconfirm } from 'antd';
import { ReloadOutlined, MergeCellsOutlined } from '@ant-design/icons';
import { scanDuplicates, listLiterature, mergeLiteratures } from '../services/literature';
import type { ScanDuplicatesResult, Literature, DuplicateGroup, MergeResult } from '../types';
import MergeDialog from './MergeDialog';

const { Text } = Typography;

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
}

/** 单次合并对话框的状态 */
interface MergeTarget {
  sourceId: string;
  targetId: string;
  sourceTitle: string;
  targetTitle: string;
}

/** 批量合并一组时的进度追踪 */
interface MergeProgress {
  groupIndex: number;
  /** 剩余待合并的 sourceId 列表 */
  queue: string[];
  targetId: string;
  targetTitle: string;
  successes: number;
  failures: number;
  total: number;
}

const DuplicateScanPanel: React.FC<DuplicateScanPanelProps> = ({ open, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanDuplicatesResult | null>(null);
  const [litMap, setLitMap] = useState<Record<string, Literature>>({});

  // 合并对话框相关
  const [mergeTarget, setMergeTarget] = useState<MergeTarget | null>(null);
  // 递增 key 强制重挂载 MergeDialog 以重置内部状态
  const [mergeRound, setMergeRound] = useState(0);
  const [mergeProgress, setMergeProgress] = useState<MergeProgress | null>(null);
  // 一键合并全部
  const [mergeAllLoading, setMergeAllLoading] = useState(false);

  // ref 避免闭包捕获 stale 值
  const mergeProgressRef = useRef<MergeProgress | null>(null);
  const litMapRef = useRef<Record<string, Literature>>({});
  litMapRef.current = litMap;

  // 防止 MergeDialog 的 onClose 在批量合并中途关闭对话框
  const skipCloseRef = useRef(false);

  const doScan = useCallback(async () => {
    setLoading(true);
    try {
      const scanResult = await scanDuplicates();
      setResult(scanResult);
      const allIds = new Set<string>();
      scanResult.groups.forEach((g) => {
        g.literature_ids.forEach((id) => allIds.add(id));
      });
      if (allIds.size > 0) {
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
  }, []);

  useEffect(() => {
    if (open) {
      setMergeTarget(null);
      setMergeProgress(null);
      mergeProgressRef.current = null;
      doScan();
    }
  }, [open, doScan]);

  /** 从 result.groups 中移除指定索引的组，并更新统计 */
  const removeGroup = useCallback((groupIndex: number) => {
    setResult((prev) => {
      if (!prev) return prev;
      const removed = prev.groups[groupIndex];
      const newGroups = prev.groups.filter((_, i) => i !== groupIndex);
      return {
        groups: newGroups,
        total_groups: newGroups.length,
        total_duplicates: prev.total_duplicates - (removed.literature_ids.length - 1),
      };
    });
  }, []);

  /** 开始合并一组（支持多成员连续合并） */
  const startMergeGroup = useCallback((groupIndex: number) => {
    const group = result?.groups[groupIndex];
    if (!group) return;
    const rep = litMapRef.current[group.representative_id];
    if (!rep) {
      message.error('未找到代表文献信息');
      return;
    }
    const sourceIds = group.literature_ids.filter((id) => id !== group.representative_id);
    if (sourceIds.length === 0) {
      message.info('该组无需合并');
      return;
    }
    const first = sourceIds[0];
    const source = litMapRef.current[first];
    const progress: MergeProgress = {
      groupIndex,
      queue: sourceIds.slice(1), // 剩余待合并
      targetId: group.representative_id,
      targetTitle: rep.title,
      successes: 0,
      failures: 0,
      total: sourceIds.length,
    };
    mergeProgressRef.current = progress;
    setMergeProgress(progress);
    setMergeTarget({
      sourceId: first,
      targetId: group.representative_id,
      sourceTitle: source?.title || first,
      targetTitle: rep.title,
    });
    setMergeRound((r) => r + 1);
  }, [result]);

  /** MergeDialog 合并成功回调 */
  const handleMerged = useCallback((mergeResult: MergeResult) => {
    // 更新 litMap
    setLitMap((prev) => {
      const next = { ...prev };
      delete next[mergeResult.deleted_source_id];
      if (mergeResult.merged_literature) {
        next[mergeResult.merged_literature.id] = mergeResult.merged_literature;
      }
      return next;
    });

    const progress = mergeProgressRef.current;
    if (!progress) return;

    const newSuccesses = progress.successes + 1;
    const remaining = [...progress.queue];

    if (remaining.length > 0) {
      // 还有剩余成员，继续合并下一个
      const nextSourceId = remaining.shift()!;
      const nextSource = litMapRef.current[nextSourceId];
      const updatedProgress: MergeProgress = { ...progress, queue: remaining, successes: newSuccesses };
      mergeProgressRef.current = updatedProgress;
      setMergeProgress(updatedProgress);
      // 标记跳过下一次 onClose，由我们控制对话框继续显示
      skipCloseRef.current = true;
      setMergeTarget({
        sourceId: nextSourceId,
        targetId: progress.targetId,
        sourceTitle: nextSource?.title || nextSourceId,
        targetTitle: progress.targetTitle,
      });
      setMergeRound((r) => r + 1);
    } else {
      // 全部合并完成
      message.success(`合并完成！成功 ${newSuccesses} 条${progress.failures > 0 ? `，跳过 ${progress.failures} 条` : ''}`);
      removeGroup(progress.groupIndex);
      mergeProgressRef.current = null;
      setMergeProgress(null);
      setMergeTarget(null);
    }
  }, [removeGroup]);

  /** MergeDialog 关闭回调 */
  const handleMergeDialogClose = useCallback(() => {
    if (skipCloseRef.current) {
      skipCloseRef.current = false;
      return; // 正在切换到下一个 source，不关闭
    }
    // 用户主动关闭对话框
    const progress = mergeProgressRef.current;
    if (progress) {
      message.info(`已中止合并：成功 ${progress.successes} 条${progress.failures > 0 ? `，跳过 ${progress.failures} 条` : ''}`);
      removeGroup(progress.groupIndex);
    }
    mergeProgressRef.current = null;
    setMergeProgress(null);
    setMergeTarget(null);
  }, [removeGroup]);

  /** 一键合并全部组 */
  const handleMergeAll = useCallback(async () => {
    if (!result || result.groups.length === 0) return;
    setMergeAllLoading(true);
    let totalSuccess = 0;
    let totalFail = 0;
    // 从后往前遍历，避免索引变化问题
    const groups = [...result.groups];
    for (let i = groups.length - 1; i >= 0; i--) {
      const group = groups[i];
      const rep = litMapRef.current[group.representative_id];
      if (!rep) continue;
      const sourceIds = group.literature_ids.filter((id) => id !== group.representative_id);
      for (const sourceId of sourceIds) {
        try {
          const mergeResult = await mergeLiteratures({
            source_id: sourceId,
            target_id: group.representative_id,
            field_choices: {},
            dp_conflict_strategy: 'keep_both',
          });
          totalSuccess++;
          // 更新 litMap
          setLitMap((prev) => {
            const next = { ...prev };
            delete next[mergeResult.deleted_source_id];
            if (mergeResult.merged_literature) {
              next[mergeResult.merged_literature.id] = mergeResult.merged_literature;
            }
            return next;
          });
        } catch {
          totalFail++;
        }
      }
      removeGroup(i);
    }
    setMergeAllLoading(false);
    message.info(`一键合并完成：成功 ${totalSuccess} 条${totalFail > 0 ? `，失败 ${totalFail} 条` : ''}`);
  }, [result, removeGroup]);

  const isMerging = mergeProgress !== null;

  const renderGroup = (group: DuplicateGroup, index: number) => {
    const members = group.literature_ids
      .map((id) => litMap[id])
      .filter((l): l is Literature => l != null);
    const rep = litMap[group.representative_id];
    const nonRepCount = group.literature_ids.length - 1;

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
          loading={isMerging && mergeProgress?.groupIndex === index}
          disabled={isMerging || mergeAllLoading}
          onClick={() => startMergeGroup(index)}
        >
          合并此组{nonRepCount > 1 ? `(${nonRepCount} 条)` : ''}
        </Button>
      </div>
    );
  };

  return (
    <>
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
                <Button size="small" icon={<ReloadOutlined />} onClick={doScan} disabled={isMerging || mergeAllLoading}>
                  重新扫描
                </Button>
              </Space>

              {result.total_groups === 0 ? (
                <Empty description="未发现重复文献" />
              ) : (
                <>
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
                  {result.groups.length > 1 && (
                    <div style={{ textAlign: 'center', marginTop: 16 }}>
                      <Popconfirm
                        title="确认一键合并全部"
                        description="将使用默认策略（差异字段选目标、空字段自动取另一方、数据点冲突保留双方）合并所有剩余组，此操作不可撤销。"
                        onConfirm={handleMergeAll}
                        okText="确认合并"
                        cancelText="取消"
                      >
                        <Button
                          type="dashed"
                          icon={<MergeCellsOutlined />}
                          loading={mergeAllLoading}
                          disabled={isMerging}
                        >
                          一键合并全部剩余组 ({result.groups.length} 组)
                        </Button>
                      </Popconfirm>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </Spin>
      </Modal>

      {/* 合并对话框（面板内部使用） */}
      <MergeDialog
        key={mergeRound}
        open={mergeTarget !== null}
        sourceId={mergeTarget?.sourceId || ''}
        targetId={mergeTarget?.targetId || ''}
        sourceTitle={mergeTarget?.sourceTitle}
        targetTitle={mergeTarget?.targetTitle}
        onClose={handleMergeDialogClose}
        onMerged={handleMerged}
      />
    </>
  );
};

export default DuplicateScanPanel;