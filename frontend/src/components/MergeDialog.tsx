import React, { useEffect, useState } from 'react';
import { Modal, Spin, Table, Radio, Alert, Button, Space, message, Typography } from 'antd';
import { previewMerge, mergeLiteratures } from '../services/literature';
import type { MergePreviewResult, MergeFieldChoice, DpConflictStrategy, MergeResult } from '../types';

const { Text } = Typography;

interface MergeDialogProps {
  open: boolean;
  sourceId: string;
  targetId: string;
  sourceTitle?: string;
  targetTitle?: string;
  onClose: () => void;
  onMerged: (result: MergeResult) => void;
}

const ARRAY_FIELDS = new Set(['keywords', 'publication_types']);

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  title_en: '英文标题',
  authors: '作者',
  journal: '期刊',
  pub_year: '发表年份',
  doi: 'DOI',
  pmid: 'PMID',
  abstract: '摘要',
  keywords: '关键词',
  region: '地区',
  province: '省份',
  publication_types: '文献类型',
  source_db: '来源数据库',
  file_path: '文件',
};

function formatValue(v: unknown): string {
  if (v == null || v === '') return '(空)';
  if (Array.isArray(v)) return v.length > 0 ? v.join(', ') : '(空)';
  if (typeof v === 'string' && v.length > 60) return v.substring(0, 60) + '...';
  return String(v);
}

const MergeDialog: React.FC<MergeDialogProps> = ({
  open, sourceId, targetId, sourceTitle, targetTitle, onClose, onMerged,
}) => {
  const [loading, setLoading] = useState(false);
  const [merging, setMerging] = useState(false);
  const [preview, setPreview] = useState<MergePreviewResult | null>(null);
  const [choices, setChoices] = useState<Record<string, MergeFieldChoice>>({});
  const [dpStrategy, setDpStrategy] = useState<DpConflictStrategy>('keep_both');

  useEffect(() => {
    if (!open || !sourceId || !targetId) return;
    setLoading(true);
    setPreview(null);
    setChoices({});
    setDpStrategy('keep_both');
    previewMerge(sourceId, targetId)
      .then((data) => {
        setPreview(data);
        // 默认：差异字段选 target，一方为空时自动选另一方
        const defaultChoices: Record<string, MergeFieldChoice> = {};
        data.field_comparison.forEach((fc) => {
          const sv = fc.source_value;
          const tv = fc.target_value;
          const sEmpty = sv == null || sv === '' || (Array.isArray(sv) && sv.length === 0);
          const tEmpty = tv == null || tv === '' || (Array.isArray(tv) && tv.length === 0);
          if (sEmpty && !tEmpty) defaultChoices[fc.field] = 'target';
          else if (!sEmpty && tEmpty) defaultChoices[fc.field] = 'source';
          else defaultChoices[fc.field] = 'target';
        });
        defaultChoices['file_path'] = 'target';
        setChoices(defaultChoices);
      })
      .catch(() => {
        message.error('获取合并预览失败');
      })
      .finally(() => setLoading(false));
  }, [open, sourceId, targetId]);

  const handleMerge = async () => {
    setMerging(true);
    try {
      const result = await mergeLiteratures({
        source_id: sourceId,
        target_id: targetId,
        field_choices: choices,
        dp_conflict_strategy: dpStrategy,
      });
      message.success(`合并成功！迁移了 ${result.moved_data_points} 条数据点`);
      onMerged(result);
      onClose();
    } catch {
      message.error('合并失败，请重试');
    } finally {
      setMerging(false);
    }
  };

  const columns = [
    {
      title: '字段',
      dataIndex: 'field',
      key: 'field',
      width: 90,
      render: (f: string) => <Text strong>{FIELD_LABELS[f] || f}</Text>,
    },
    {
      title: '源文献',
      dataIndex: 'source_value',
      key: 'source_value',
      render: (v: unknown, _r: unknown, idx: number) => {
        const fc = preview?.field_comparison[idx];
        return (
          <span style={{ color: fc?.differs ? '#fa8c16' : undefined }}>
            {formatValue(v)}
          </span>
        );
      },
    },
    {
      title: '目标文献',
      dataIndex: 'target_value',
      key: 'target_value',
      render: (v: unknown, _r: unknown, idx: number) => {
        const fc = preview?.field_comparison[idx];
        return (
          <span style={{ color: fc?.differs ? '#fa8c16' : undefined }}>
            {formatValue(v)}
          </span>
        );
      },
    },
    {
      title: '保留',
      key: 'choice',
      width: 140,
      render: (_v: unknown, _r: unknown, idx: number) => {
        const fc = preview?.field_comparison[idx];
        if (!fc) return null;
        const fieldName = fc.field;
        const isArr = ARRAY_FIELDS.has(fieldName);
        return (
          <Radio.Group
            size="small"
            value={choices[fieldName] || 'target'}
            onChange={(e) => setChoices({ ...choices, [fieldName]: e.target.value })}
          >
            <Radio.Button value="source">源</Radio.Button>
            <Radio.Button value="target">目标</Radio.Button>
            {isArr && <Radio.Button value="merge">合并</Radio.Button>}
          </Radio.Group>
        );
      },
    },
  ];

  return (
    <Modal
      title="合并文献"
      open={open}
      onCancel={onClose}
      width={800}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="merge" type="primary" loading={merging} onClick={handleMerge} danger>
          确认合并
        </Button>,
      ]}
    >
      <Spin spinning={loading}>
        {preview && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                <Space>
                  <span>源文献: <Text strong>{sourceTitle || sourceId}</Text> ({preview.source_data_point_count} 条数据点)</span>
                  <span>→</span>
                  <span>目标文献: <Text strong>{targetTitle || targetId}</Text> ({preview.target_data_point_count} 条数据点)</span>
                </Space>
              }
            />

            <Table
              dataSource={preview.field_comparison}
              rowKey="field"
              size="small"
              pagination={false}
              columns={columns}
              scroll={{ y: 300 }}
            />

            {preview.total_conflicts > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 12 }}
                message={`发现 ${preview.total_conflicts} 条冲突数据点（疾病+省份+年份+类型相同）${preview.total_conflicts > preview.conflicts.length ? '（仅显示前 50 条）' : ''}`}
                description={
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Radio.Group
                      value={dpStrategy}
                      onChange={(e) => setDpStrategy(e.target.value)}
                    >
                      <Radio value="keep_both">保留双方数据点</Radio>
                      <Radio value="prefer_target">优先保留目标数据点</Radio>
                      <Radio value="prefer_source">优先保留源数据点</Radio>
                    </Radio.Group>
                  </Space>
                }
              />
            )}

            <Alert
              type="error"
              showIcon
              style={{ marginTop: 12 }}
              message="⚠ 合并后源文献将被删除，其数据点将迁移到目标文献"
            />
          </>
        )}
      </Spin>
    </Modal>
  );
};

export default MergeDialog;
