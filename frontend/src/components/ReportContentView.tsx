import React, { useEffect, useState, useMemo } from 'react';
import { Button, Input, Space, message } from 'antd';
import { EditOutlined, SaveOutlined, CloseOutlined, MenuOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { updateReport } from '../services/map';

interface TocItem {
  id: string;
  text: string;
  level: number;
}

function parseToc(markdown: string): TocItem[] {
  const headingRegex = /^(#{2,3})\s+(.+)$/gm;
  const items: TocItem[] = [];
  let match: RegExpExecArray | null;
  while ((match = headingRegex.exec(markdown)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
    items.push({ id, text, level });
  }
  return items;
}

const TOC_WIDTH = 220;

const markdownStyle: React.CSSProperties = {
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif',
  fontSize: 15,
  lineHeight: 1.8,
  color: '#333',
  padding: '24px 32px',
};

interface Props {
  content: string;
  editable?: boolean;
  reportId?: string;
  onSaved?: (newContent: string) => void;
}

const ReportContentView: React.FC<Props> = ({ content, editable = false, reportId, onSaved }) => {
  const toc = useMemo(() => parseToc(content), [content]);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(content);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEditContent(content);
    setEditing(false);
  }, [content]);

  const handleScrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleSave = async () => {
    if (!reportId) return;
    setSaving(true);
    try {
      await updateReport(reportId, { content: editContent });
      setEditing(false);
      message.success('报告已保存');
      onSaved?.(editContent);
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', gap: 0, minHeight: 400 }}>
      <div style={{
        width: TOC_WIDTH, minWidth: TOC_WIDTH,
        borderRight: '1px solid #f0f0f0', padding: '12px 0',
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '0 12px 8px', fontWeight: 600, fontSize: 14, color: '#666', display: 'flex', alignItems: 'center', gap: 6 }}>
          <MenuOutlined /> 目录
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {toc.length === 0 ? (
            <div style={{ padding: '8px 4px', color: '#999', fontSize: 13 }}>无标题</div>
          ) : (
            toc.map((item) => (
              <div
                key={item.id}
                onClick={() => handleScrollTo(item.id)}
                style={{
                  padding: '4px 8px', paddingLeft: (item.level - 1) * 16 + 4,
                  fontSize: 13, color: '#1890ff', cursor: 'pointer',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  borderRadius: 4, transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f0f5ff')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '')}
              >
                {item.text}
              </div>
            ))
          )}
        </div>
        {editable && (
          <div style={{ padding: '12px', borderTop: '1px solid #f0f0f0' }}>
            {editing ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Button icon={<SaveOutlined />} type="primary" block onClick={handleSave} loading={saving}>保存</Button>
                <Button icon={<CloseOutlined />} block onClick={() => { setEditing(false); setEditContent(content); }}>取消</Button>
              </Space>
            ) : (
              <Button icon={<EditOutlined />} block onClick={() => { setEditContent(content); setEditing(true); }}>编辑</Button>
            )}
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {editing ? (
          <Input.TextArea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            style={{ fontFamily: 'Consolas, Monaco, "Courier New", monospace', fontSize: 14, lineHeight: 1.6, border: 'none', resize: 'none', minHeight: 400 }}
            autoSize={{ minRows: 20 }}
          />
        ) : (
          <div className="markdown-preview" style={markdownStyle}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h2: ({ children, ...props }) => {
                  const text = String(children);
                  const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
                  return <h2 id={id} {...props}>{children}</h2>;
                },
                h3: ({ children, ...props }) => {
                  const text = String(children);
                  const id = text.replace(/\s+/g, '-').replace(/[^\w\u4e00-\u9fff-]/g, '');
                  return <h3 id={id} {...props}>{children}</h3>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportContentView;
