/**
 * SnapshotCitation：分析图表"引用"图标 + 弹层。
 *
 * - 各图卡片右上角提供"引用"图标；
 * - 点击弹出：快照号（token）、数据截至说明、GBT7714 / BibTeX 引用文本（可一键复制）；
 * - 数据截至日期优先取后端 citation 文本，本组件仅作前端兜底展示。
 */
import React, { useCallback, useState } from 'react';
import { Button, Input, Modal, Space, Tooltip, Typography, message } from 'antd';
import { CopyOutlined, LinkOutlined } from '@ant-design/icons';
import api from '../services/api';

const { Text, Paragraph } = Typography;

interface SnapshotCitationProps {
  /** 后端返回的 meta.snapshot_token；为空时点击提示需先查询 */
  token?: string | null;
  /** 图表/模块标题（弹层标题用） */
  title?: string;
}

const SnapshotCitation: React.FC<SnapshotCitationProps> = ({ token, title }) => {
  const [open, setOpen] = useState(false);
  const [gbt, setGbt] = useState('');
  const [bib, setBib] = useState('');
  const [loading, setLoading] = useState(false);

  const copy = useCallback(async (text: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制到剪贴板');
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      message.success('已复制到剪贴板');
    }
  }, []);

  const openModal = useCallback(async () => {
    if (!token) {
      message.info('当前图表尚无分析快照，请先完成查询');
      return;
    }
    setOpen(true);
    setLoading(true);
    setGbt('');
    setBib('');
    try {
      const [g, b] = await Promise.all([
        api.get<string>(`/analysis/snapshot/${token}/citation`, { params: { style: 'gbt7714' }, responseType: 'text' }),
        api.get<string>(`/analysis/snapshot/${token}/citation`, { params: { style: 'bibtex' }, responseType: 'text' }),
      ]);
      setGbt(g.data || '');
      setBib(b.data || '');
    } catch (e) {
      console.error('[SnapshotCitation] 获取引用文本失败:', e);
      message.error('获取引用文本失败');
    } finally {
      setLoading(false);
    }
  }, [token]);

  const shortToken = token ? `${token.slice(0, 8)}…` : '';
  const dataAsOf = new Date().toISOString().slice(0, 10);

  return (
    <>
      <Tooltip title="引用本图（快照号/引用文本）">
        <Button type="link" size="small" icon={<LinkOutlined />} onClick={openModal} />
      </Tooltip>
      <Modal
        title={title ? `引用 — ${title}` : '引用与分析快照'}
        open={open}
        onCancel={() => setOpen(false)}
        footer={[
          <Button key="close" onClick={() => setOpen(false)}>
            关闭
          </Button>,
        ]}
        width={720}
      >
        {loading ? (
          <div style={{ padding: 24, textAlign: 'center' }}>加载中…</div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <div>
              <Text strong>快照号（snapshot token）</Text>
              <Input.Group compact style={{ marginTop: 4, display: 'flex' }}>
                <Input value={token || '—'} readOnly style={{ flex: 1 }} />
                <Button icon={<CopyOutlined />} onClick={() => token && copy(token)}>
                  复制
                </Button>
              </Input.Group>
            </div>
            <div>
              <Text type="secondary">
                数据截至：{dataAsOf}。凭快照号可在分析接口重放相同结果（数据更新后会产生新快照号）。
              </Text>
            </div>
            <div>
              <Text strong>引用文本（GB/T 7714）</Text>
              <Paragraph
                style={{
                  background: '#fafafa',
                  padding: 8,
                  borderRadius: 4,
                  border: '1px solid #f0f0f0',
                  marginBottom: 4,
                }}
                copyable={{ text: gbt }}
              >
                {gbt || '（无）'}
              </Paragraph>
              <Button size="small" icon={<CopyOutlined />} onClick={() => copy(gbt)}>
                复制 GBT7714
              </Button>
            </div>
            <div>
              <Text strong>BibTeX</Text>
              <Paragraph
                style={{
                  background: '#fafafa',
                  padding: 8,
                  borderRadius: 4,
                  border: '1px solid #f0f0f0',
                  fontFamily: 'monospace',
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  marginBottom: 4,
                }}
                copyable={{ text: bib }}
              >
                {bib || '（无）'}
              </Paragraph>
              <Button size="small" icon={<CopyOutlined />} onClick={() => copy(bib)}>
                复制 BibTeX
              </Button>
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {shortToken ? `引用标识：${shortToken}` : ''}
            </Text>
          </Space>
        )}
      </Modal>
    </>
  );
};

export default SnapshotCitation;
