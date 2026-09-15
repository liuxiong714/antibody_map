import React, { useEffect, useRef, useState } from 'react';
import { Modal } from 'antd';
import FilePreview from './FilePreview';

interface PdfPreviewModalProps {
  open: boolean;
  literatureId: string | null;
  literatureTitle?: string;
  filePath?: string | null;
  onClose: () => void;
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
}) => {
  const offsetRef = useRef({ x: 0, y: 0 });
  const cleanupRef = useRef<(() => void) | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

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
      footer={null}
      width="90vw"
      style={{ top: 20, transform: `translate(${dragOffset.x}px, ${dragOffset.y}px)` }}
      destroyOnHidden
      centered={false}
      styles={{ body: { padding: 8, height: 'calc(80vh - 100px)', overflow: 'hidden', display: 'flex', flexDirection: 'column' } }}
    >
      {literatureId && (
        <FilePreview
          literatureId={literatureId}
          filePath={filePath ?? null}
          defaultScale={1.2}
          maxHeight="calc(80vh - 100px)"
        />
      )}
    </Modal>
  );
};

export default PdfPreviewModal;
