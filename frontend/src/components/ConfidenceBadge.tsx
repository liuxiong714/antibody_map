import React from 'react';
import { Tag } from 'antd';
import { CONFIDENCE_META } from '../utils/constants';

interface Props {
  confidence: string;
}

const ConfidenceBadge: React.FC<Props> = ({ confidence }) => {
  const meta = CONFIDENCE_META[confidence] || { color: 'default', label: confidence };
  return <Tag color={meta.color}>{meta.label}</Tag>;
};

export default ConfidenceBadge;
