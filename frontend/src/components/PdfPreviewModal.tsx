import React, { useEffect, useRef, useState } from 'react';
import { Modal, Button, Space, Tooltip, Popconfirm, Segmented } from 'antd';
import {
  ThunderboltOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import FilePreview from './FilePreview';
import type { PdfViewerHandle } from './PdfViewer';

interface PdfPreviewModalProps {
  open: boolean;
  literatureId: string | null;
  literatureTitle?: string;
  filePath?: string | null;
  onClose: () => void;
  /** AI 提取按钮 */
  onExtract?: () => void;
  /** 删除按钮（带二次确认） */
  onDelete?: () => void;
  /** 切换上一篇 */
  onPrev?: () => void;
  /** 切换下一篇 */
  onNext?: () => void;
  /** 上一篇是否可用 */
  hasPrev?: boolean;
  /** 下一篇是否可用 */
  hasNext?: boolean;
}

/**
 * 简单可拖拽 Modal：按住标题栏可整体移动位置。
 * 实现方式：open=true 时用 ref 绑定 Modal root，监听 header mousedown → document mousemove/mouseup，
 * 偏移量通过 inline style 的 transform 应用；关闭后自动清理。
 * 不引 react-draggable，零依赖，约 25 行。
 */
const PdfPreviewModal: React.FC<PdfPreviewModalProps> = ({
  open,
  literatureId,
  literatureTitle,
  filePath,
  onClose,
  onExtract,
  onDelete,
  onPrev,
  onNext,
  hasPrev = true,
  hasNext = true,
}) => {
  const offsetRef = useRef({ x: 0, y: 0 });
  const cleanupRef = useRef<(() => void) | null>(null);
  const pdfRef = useRef<PdfViewerHandle>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [pageLayout, setPageLayout] = useState<'single' | 'double'>('single');

  // 全局键盘快捷键：仅 Modal 打开时监听
  useEffect(() => {
    if (!open) return;
    const isEditable = (el: EventTarget | null) => {
      const n = el as HTMLElement | null;
      if (!n) return false;
      const tag = (n.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return true;
      if (n.isContentEditable) return true;
      return false;
    };
    const handler = (e: KeyboardEvent) => {
      // PDF 预览里可能有文本选区，焦点在可编辑元素上时跳过
      if (isEditable(e.target)) return;

      const mod = e.ctrlKey || e.metaKey; // Ctrl (Win) / Cmd (Mac)
      const viewer = pdfRef.current;

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          if (onPrev && hasPrev) onPrev();
          break;
        case 'ArrowRight':
          e.preventDefault();
          if (onNext && hasNext) onNext();
          break;
        case 'PageUp':
          e.preventDefault();
          if (viewer) {
            const cur = viewer.getCurrentPage();
            if (cur > 1) viewer.scrollToPage(cur - 1);
          }
          break;
        case 'PageDown':
          e.preventDefault();
          if (viewer) {
            const total = viewer.getNumPages();
            const cur = viewer.getCurrentPage();
            if (cur < total) viewer.scrollToPage(cur + 1);
          }
          break;
        case 'Delete':
          if (mod) {
            // Ctrl/Cmd + Delete：删除（危险操作，带修饰键防误触）
            e.preventDefault();
            onDelete?.();
          }
          break;
        case 'e':
        case 'E':
          if (mod) {
            e.preventDefault();
            onExtract?.();
          }
          break;
        default:
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onPrev, onNext, onExtract, onDelete, hasPrev, hasNext]);

  useEffect(() => {
    if (!open) {
      offsetRef.current = { x: 0, y: 0 };
      setDragOffset({ x: 0, y: 0 });
      return;
    }
    // Modal 通过 Portal 挂载到 document.body，Portal 容器可能延迟一帧才就绪
    // 用 setTimeout 兜底等待（同时尝试多帧重试直到找到 DOM）
    let frameCount = 0;
    let cancelled = false;

    const bind = () => {
      if (cancelled) return;
      frameCount++;
      const modalEl = document.querySelector('.ant-modal-wrap .ant-modal') as HTMLElement | null;
      const headerEl = modalEl?.querySelector('.ant-modal-header') as HTMLElement | null;
      if (!modalEl || !headerEl) {
        if (frameCount < 10) {
          requestAnimationFrame(bind);
        }
        return;
      }
      headerEl.style.cursor = 'move';

      const onMouseDown = (e: MouseEvent) => {
        if (e.button !== 0) return;
        const target = e.target as HTMLElement;
        if (target.closest('button, input, textarea, a')) return;

        const startX = e.clientX;
        const startY = e.clientY;
        const base = offsetRef.current;

        const onMove = (ev: MouseEvent) => {
          offsetRef.current = {
            x: base.x + (ev.clientX - startX),
            y: base.y + (ev.clientY - startY),
          };
          setDragOffset({ ...offsetRef.current });
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        e.preventDefault();
      };

      headerEl.addEventListener('mousedown', onMouseDown);
      cleanupRef.current = () => {
        headerEl.style.cursor = '';
        headerEl.removeEventListener('mousedown', onMouseDown);
      };
    };

    requestAnimationFrame(bind);
    return () => {
      cancelled = true;
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [open]);

  return (
    <Modal
      title={literatureTitle ? `预览: ${literatureTitle}` : '文件预览'}
      open={open}
      onCancel={onClose}
      width="90vw"
      style={{ top: 20, transform: `translate(${dragOffset.x}px, ${dragOffset.y}px)` }}
      destroyOnHidden
      centered={false}
      styles={{ body: { padding: 8, height: 'calc(80vh - 100px)', overflow: 'hidden', display: 'flex', flexDirection: 'column' } }}
      footer={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <Space size={10}>
            {/* 视图模式切换 */}
            <Segmented
              size="small"
              value={pageLayout}
              onChange={(v) => setPageLayout(v as 'single' | 'double')}
              options={[
                { label: '单页', value: 'single' },
                { label: '双页', value: 'double' },
              ]}
            />
            <span style={{ fontSize: 12, color: '#888' }}>
              PageUp/Down 翻页
            </span>
          </Space>
          <Space size={8}>
            {onPrev && (
              <Tooltip title="上一篇 (←)">
                <Button
                  icon={<ArrowLeftOutlined />}
                  onClick={onPrev}
                  disabled={!hasPrev}
                >
                  上一篇
                </Button>
              </Tooltip>
            )}
            {onNext && (
              <Tooltip title="下一篇 (→)">
                <Button
                  icon={<ArrowRightOutlined />}
                  onClick={onNext}
                  disabled={!hasNext}
                >
                  下一篇
                </Button>
              </Tooltip>
            )}
          </Space>
          <Space size={8}>
            {onExtract && (
              <Tooltip title="AI 提取：调用模型从本文献提取抗体数据点 (Ctrl+E)">
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  onClick={onExtract}
                >
                  AI 提取
                </Button>
              </Tooltip>
            )}
            {onDelete && (
              <Popconfirm
                title="确定删除该文献？"
                description="删除后文献记录、PDF 文件、数据点会一并清除，不可恢复。"
                okText="删除"
                okType="danger"
                cancelText="取消"
                onConfirm={onDelete}
              >
                <Tooltip title="删除这条文献记录 (Ctrl+Delete)">
                  <Button danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Tooltip>
              </Popconfirm>
            )}
          </Space>
        </div>
      }
    >
      {literatureId && (
        <FilePreview
          literatureId={literatureId}
          filePath={filePath ?? null}
          defaultScale={1.2}
          maxHeight="calc(80vh - 100px)"
          pageLayout={pageLayout}
          pdfRef={pdfRef}
        />
      )}
    </Modal>
  );
};

export default PdfPreviewModal;
