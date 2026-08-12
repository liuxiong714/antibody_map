import React from 'react';
import { Modal } from 'antd';
import PdfViewer from './PdfViewer';

interface PdfPreviewModalProps {
  open: boolean;
  literatureId: string | null;
  literatureTitle?: string;
  onClose: () => void;
}

const PdfPreviewModal: React.FC<PdfPreviewModalProps> = ({
  open,
  literatureId,
  literatureTitle,
  onClose,
}) => {
  return (
    <Modal
      title={literatureTitle ? `预览: ${literatureTitle}` : 'PDF 预览'}
      open={open}
      onCancel={onClose}
      footer={null}
      width="90vw"
      style={{ top: 20 }}
      destroyOnHidden
      centered={false}
    >
      <PdfViewer
        literatureId={literatureId}
        defaultScale={1.2}
        maxHeight="calc(80vh - 100px)"
      />
    </Modal>
  );
};

export default PdfPreviewModal;
