import React from 'react';
import { Select } from 'antd';
import { DATA_TYPE_LABEL } from '../utils/constants';

interface Props {
  value: string;
  onChange: (v: string) => void;
  style?: React.CSSProperties;
}

const MapSelector: React.FC<Props> = ({ value, onChange, style }) => {
  const options = Object.entries(DATA_TYPE_LABEL).map(([k, v]) => ({ value: k, label: v }));
  return (
    <Select
      style={style || { width: 180 }}
      placeholder="数据类型"
      value={value || undefined}
      onChange={(v) => onChange(v || '')}
      allowClear
      options={options}
    />
  );
};

export default MapSelector;
