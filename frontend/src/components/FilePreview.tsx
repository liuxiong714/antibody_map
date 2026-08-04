import React, { useState, useEffect, useCallback } from 'react';
import { Button, Space, Spin, message, Empty, Typography } from 'antd';
import { DownloadOutlined, FileTextOutlined } from '@ant-design/icons';
import PdfViewer from './PdfViewer';

const { Text, Paragraph } = Typography;

interface FilePreviewProps {
  literatureId: string | null;
  filePath: string | null;
  defaultScale?: number;
  maxHeight?: string;
}

/**
 * 通用文件预览组件：
 * - PDF: 使用 PdfViewer 渲染
 * - TXT/HTML: 直接渲染文本内容
 * - DOCX/PPTX/XLSX/EPUB: 调用 source-text 接口显示提取后的纯文本
 * - CAJ/其他: 提示下载查看
 */
const FilePreview: React.FC<FilePreviewProps> = ({
  literatureId,
  filePath,
  defaultScale = 0.8,
  maxHeight = '100%',
}) => {
  const ext = filePath?.toLowerCase().match(/\.([^.]+)$/)?.[1] || '';
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);

  const isPdf = ext === 'pdf';
  const isTextLike = ['txt', 'html', 'htm'].includes(ext);
  const isOfficeLike = ['docx', 'pptx', 'xlsx', 'epub'].includes(ext);
  const isUnsupported = ['caj'].includes(ext);

  // 日志：初始化预览类型判定
  console.log(`[FilePreview] 初始化预览: literatureId=${literatureId}, ext=${ext || '(无)'}, isPdf=${isPdf}, isTextLike=${isTextLike}, isOfficeLike=${isOfficeLike}, isUnsupported=${isUnsupported}`);

  const fetchTextContent = useCallback(async () => {
    if (!literatureId || (!isTextLike && !isOfficeLike)) return;
    console.log(`[FilePreview] 开始拉取文本内容: literatureId=${literatureId}, ext=${ext}, strategy=${isOfficeLike ? 'source-text优先' : 'source-text+file回退'}`);
    setTextLoading(true);
    try {
      // 先尝试 source-text 接口（提取后的文本）
      const resp = await fetch(`/api/v1/literatures/${literatureId}/source-text`);
      console.log(`[FilePreview] source-text 响应: status=${resp.status}, ok=${resp.ok}`);
      if (resp.ok) {
        const json = await resp.json();
        if (json.data?.full_text) {
          console.log(`[FilePreview] 使用 full_text: length=${json.data.full_text.length}`);
          setTextContent(json.data.full_text);
          return;
        }
        if (json.data?.snippet) {
          console.log(`[FilePreview] 使用 snippet: length=${json.data.snippet.length}`);
          setTextContent(json.data.snippet);
          return;
        }
        console.warn('[FilePreview] source-text 返回但无 full_text/snippet');
      }
      // 如果 source-text 不存在，对于 txt/html 直接获取文件内容
      if (isTextLike) {
        console.log(`[FilePreview] 回退到 /file 直接获取文本: literatureId=${literatureId}`);
        const fileResp = await fetch(`/api/v1/literatures/${literatureId}/file`);
        console.log(`[FilePreview] /file 响应: status=${fileResp.status}, ok=${fileResp.ok}`);
        if (fileResp.ok) {
          const text = await fileResp.text();
          console.log(`[FilePreview] /file 文本加载成功: length=${text.length}`);
          setTextContent(text);
          return;
        }
      }
      console.warn(`[FilePreview] 文本内容获取失败，置为 null`);
      setTextContent(null);
    } catch (e) {
      console.error('[FilePreview] 获取文本异常:', e);
      setTextContent(null);
    } finally {
      setTextLoading(false);
    }
  }, [literatureId, isTextLike, isOfficeLike, ext]);

  useEffect(() => {
    if (isTextLike || isOfficeLike) {
      fetchTextContent();
    }
  }, [fetchTextContent, isTextLike, isOfficeLike]);

  // PDF: 使用 PdfViewer
  if (isPdf) {
    return (
      <PdfViewer
        literatureId={literatureId}
        defaultScale={defaultScale}
        maxHeight={maxHeight}
      />
    );
  }

  // TXT/HTML/DOCX/PPTX/XLSX/EPUB: 显示文本内容
  if (isTextLike || isOfficeLike) {
    if (textLoading) {
      return (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin tip="加载文本内容中..." />
        </div>
      );
    }
    if (textContent) {
      const isHtml = ext === 'html' || ext === 'htm';
      return (
        <div
          style={{
            height: '100%',
            overflow: 'auto',
            padding: 16,
            background: '#fafafa',
          }}
        >
          <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <FileTextOutlined style={{ color: '#1890ff' }} />
              <Text type="secondary" style={{ fontSize: 13 }}>
                {ext.toUpperCase()} 格式 — 文本预览{isOfficeLike ? '（来自解析后文本）' : ''}
              </Text>
            </Space>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={`/api/v1/literatures/${literatureId}/download`}
            >
              下载原文件
            </Button>
          </div>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontSize: 14,
              lineHeight: 1.8,
              fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace",
              margin: 0,
              padding: 12,
              background: '#fff',
              borderRadius: 6,
              border: '1px solid #e8e8e8',
              minHeight: 200,
            }}
          >
            {textContent}
          </pre>
        </div>
      );
    }
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <Empty description="文本内容暂不可用（可能尚未提取）" />
        <Button
          type="link"
          icon={<DownloadOutlined />}
          href={`/api/v1/literatures/${literatureId}/download`}
        >
          下载文件查看
        </Button>
      </div>
    );
  }

  // CAJ 或其他不支持的格式
  return (
    <div style={{ textAlign: 'center', padding: '60px 0' }}>
      <Empty description={`${ext.toUpperCase()} 格式暂不支持在线预览`} />
      <Button
        type="link"
        icon={<DownloadOutlined />}
        href={`/api/v1/literatures/${literatureId}/download`}
      >
        下载文件查看
      </Button>
    </div>
  );
};

export default FilePreview;
