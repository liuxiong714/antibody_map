import React from 'react';
import { Select } from 'antd';
import { DISEASES } from '../utils/constants';

interface Props {
  value: string;
  onChange: (v: string) => void;
  allowClear?: boolean;
  style?: React.CSSProperties;
}

const DiseaseSelector: React.FC<Props> = ({ value, onChange, allowClear = true, style }) => (
  <Select
    style={style || { width: 180 }}
    placeholder="选择疾病"
    value={value || undefined}
    onChange={(v) => onChange(v || '')}
    allowClear={allowClear}
    options={DISEASES.map((d) => ({ value: d.key, label: d.name_cn }))}
  />
);

export default DiseaseSelector;
