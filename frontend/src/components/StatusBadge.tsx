import React from 'react';
import { Tag } from 'antd';
import { EXTRACTION_STATUS_META } from '../utils/constants';

interface Props {
  status: string;
}

const StatusBadge: React.FC<Props> = ({ status }) => {
  const meta = EXTRACTION_STATUS_META[status] || { color: 'default', label: status };
  return <Tag color={meta.color}>{meta.label}</Tag>;
};

export default StatusBadge;
