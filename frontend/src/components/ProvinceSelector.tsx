import React from 'react';
import { Select } from 'antd';
import { PROVINCES } from '../utils/constants';

interface Props {
  value: string;
  onChange: (v: string) => void;
  allowClear?: boolean;
  style?: React.CSSProperties;
}

const ProvinceSelector: React.FC<Props> = ({ value, onChange, allowClear = true, style }) => (
  <Select
    showSearch
    style={style || { width: 160 }}
    placeholder="选择省份"
    value={value || undefined}
    onChange={(v) => onChange(v || '')}
    allowClear={allowClear}
    options={PROVINCES.map((p) => ({ value: p, label: p }))}
    filterOption={(input, option) => (option?.label as string)?.includes(input)}
  />
);

export default ProvinceSelector;
