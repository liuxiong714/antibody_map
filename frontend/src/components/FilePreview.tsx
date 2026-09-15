import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button, Space, Spin, message, Empty, Typography, Upload } from 'antd';
import { DownloadOutlined, FileTextOutlined, UploadOutlined } from '@ant-design/icons';
import { uploadLiteratureFile } from '../services/literature';
import PdfViewer from './PdfViewer';

const { Text } = Typography;

interface FilePreviewProps {
  literatureId: string | null;
  filePath: string | null;
  defaultScale?: number;
  maxHeight?: string;
  onFileUploaded?: () => void;
}

/**
 * 通用文件预览组件：
 * - PDF: 使用 PdfViewer 渲染
 * - TXT/HTML: 直接渲染文本内容
 * - DOCX/PPTX/XLSX/EPUB: 调用 source-text 接口显示提取后的纯文本
 * - CAJ/其他: 提示导入关联文件
 * - 无文件时: 显示"导入关联文件"按钮，供用户手动上传本地文件
 */
const FilePreview: React.FC<FilePreviewProps> = ({
  literatureId,
  filePath,
  defaultScale = 0.8,
  maxHeight = '100%',
  onFileUploaded,
}) => {
  const ext = filePath?.toLowerCase().match(/\.([^.]+)$/)?.[1] || '';
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isPdf = ext === 'pdf' || ext === 'caj';
  // HTML/HTM: 使用 iframe srcdoc 渲染原始排版（保留 <table>/<img>/样式），
  // 通过 fetch 带 token header 绕开 iframe 不支持鉴权 header 的问题；
  // sandbox 隔离与主应用 DOM，防止外部 HTML 污染 React 界面。
  const isHtmlLike = ['html', 'htm'].includes(ext);
  const isTextLike = ['txt'].includes(ext);
  const isOfficeLike = ['docx', 'pptx', 'xlsx', 'epub'].includes(ext);
  const hasFile = !!filePath;

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !literatureId) return;
    setUploading(true);
    try {
      await uploadLiteratureFile(literatureId, file);
      message.success('文件已成功关联到该文献');
      onFileUploaded?.();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '上传失败';
      message.error(detail);
    } finally {
      setUploading(false);
      // 重置 file input 以允许重复选择同一文件
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const authFetch = useCallback((url: string) => {
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return fetch(url, { headers });
  }, []);

  const fetchTextContent = useCallback(async () => {
    if (!literatureId || (!isHtmlLike && !isTextLike && !isOfficeLike)) return;
    setTextLoading(true);
    try {
      const resp = await authFetch(`/api/v1/literatures/${literatureId}/source-text`);
      if (resp.ok) {
        const json = await resp.json();
        if (json.data?.full_text) {
          setTextContent(json.data.full_text);
          return;
        }
        if (json.data?.snippet) {
          setTextContent(json.data.snippet);
          return;
        }
      }
      // HTML/TXT 直接拉原文件（HTML 用于 srcdoc 渲染；TXT 用于 <pre> 展示）
      if (isHtmlLike || isTextLike) {
        const fileResp = await authFetch(`/api/v1/literatures/${literatureId}/file`);
        if (fileResp.ok) {
          const text = await fileResp.text();
          setTextContent(text);
          return;
        }
      }
      setTextContent(null);
    } catch (e) {
      console.error('[FilePreview] 获取文本异常:', e);
      setTextContent(null);
    } finally {
      setTextLoading(false);
    }
  }, [literatureId, isHtmlLike, isTextLike, isOfficeLike, authFetch]);

  useEffect(() => {
    if (isHtmlLike || isTextLike || isOfficeLike) {
      fetchTextContent();
    }
  }, [fetchTextContent, isHtmlLike, isTextLike, isOfficeLike]);

  // 通用的"导入关联文件"按钮
  const renderImportButton = (label: string) => (
    <div style={{ marginTop: 16 }}>
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
        accept=".pdf,.caj,.epub,.docx,.pptx,.xlsx,.txt,.html,.htm"
      />
      <Button
        type="primary"
        icon={<UploadOutlined />}
        loading={uploading}
        onClick={() => fileInputRef.current?.click()}
      >
        {uploading ? '上传中...' : label}
      </Button>
    </div>
  );

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

  // HTML/HTM: 使用 iframe srcdoc 渲染原始 HTML（保留排版、表格、图片）
  if (isHtmlLike) {
    if (textLoading) {
      return (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin tip="加载 HTML 内容中...">
            <div style={{ height: 80 }} />
          </Spin>
        </div>
      );
    }
    if (textContent) {
      return (
        <div
          style={{
            height: '100%',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            background: '#fff',
          }}
        >
          <div
            style={{
              padding: '6px 12px',
              borderBottom: '1px solid #e8e8e8',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: '#fafafa',
              fontSize: 12,
              color: '#888',
            }}
          >
            <Space size={8}>
              <FileTextOutlined style={{ color: '#1890ff' }} />
              <span>{ext.toUpperCase()} 格式 — 原始 HTML 渲染</span>
            </Space>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={`/api/v1/literatures/${literatureId}/download`}
            >
              下载原文件
            </Button>
          </div>
          <iframe
            title="文献预览"
            srcDoc={textContent}
            // sandbox 隔离: 允许同源脚本（大部分 HTML 报告），允许表单，
            // 允许新开窗口（target=_blank 链接），但禁止访问顶层 DOM / cookie
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
            style={{
              flex: 1,
              width: '100%',
              border: 'none',
              background: '#fff',
            }}
          />
        </div>
      );
    }
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <Empty description="HTML 内容暂不可用（可能尚未提取）" />
        {renderImportButton('导入关联文件')}
      </div>
    );
  }

  // TXT/DOCX/PPTX/XLSX/EPUB: 显示文本内容
  if (isTextLike || isOfficeLike) {
    if (textLoading) {
      return (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin tip="加载文本内容中...">
            <div style={{ height: 80 }} />
          </Spin>
        </div>
      );
    }
    if (textContent) {
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
        {renderImportButton('导入关联文件')}
      </div>
    );
  }

  // 无文件或文件格式不支持
  return (
    <div style={{ textAlign: 'center', padding: '60px 0' }}>
      <Empty description={hasFile ? `${ext.toUpperCase()} 格式暂不支持在线预览` : '暂无关联文件'} />
      {renderImportButton('导入关联文件')}
    </div>
  );
};

export default FilePreview;
