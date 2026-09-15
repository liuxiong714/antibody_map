import React from 'react';
import { Modal } from 'antd';
import FilePreview from './FilePreview';

interface PdfPreviewModalProps {
  open: boolean;
  literatureId: string | null;
  literatureTitle?: string;
  filePath?: string | null;
  onClose: () => void;
}

const PdfPreviewModal: React.FC<PdfPreviewModalProps> = ({
  open,
  literatureId,
  literatureTitle,
  filePath,
  onClose,
}) => {
  // 统一使用 FilePreview（支持 PDF / HTML / TXT / DOCX 等全部格式），
  // 替代旧的 Pdf-only 实现，避免非 PDF 文件（如 Centre for Health Protection 的 .htm）
  // 在列表页点击预览时弹出 Modal 却渲染不出内容。
  return (
    <Modal
      title={literatureTitle ? `预览: ${literatureTitle}` : '文件预览'}
      open={open}
      onCancel={onClose}
      footer={null}
      width="90vw"
      style={{ top: 20 }}
      destroyOnHidden
      centered={false}
      styles={{ body: { padding: 8, minHeight: 400, maxHeight: '80vh', overflow: 'auto' } }}
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
