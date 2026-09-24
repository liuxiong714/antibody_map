import React from 'react';
import { Select } from 'antd';
import { DISEASES } from '../utils/constants';

interface BaseProps {
  allowClear?: boolean;
  multiple?: boolean;
  placeholder?: string;
  style?: React.CSSProperties;
}

interface SingleProps extends BaseProps {
  multiple?: false;
  value: string;
  onChange: (v: string) => void;
}

interface MultipleProps extends BaseProps {
  multiple: true;
  value: string[];
  onChange: (v: string[]) => void;
}

type Props = SingleProps | MultipleProps;

const DiseaseSelector: React.FC<Props> = (props) => {
  const { allowClear = true, placeholder, style } = props;
  const multiple = props.multiple === true;

  if (multiple) {
    const { value, onChange } = props as MultipleProps;
    return (
      <Select
        showSearch
        mode="multiple"
        style={style || { width: 280 }}
        placeholder={placeholder || '选择疾病（可多选）'}
        value={value.length > 0 ? value : undefined}
        onChange={(v) => onChange(v || [])}
        allowClear={allowClear}
        maxTagCount="responsive"
        options={DISEASES.map((d) => ({ value: d.key, label: d.name_cn }))}
        filterOption={(input, option) => (option?.label as string)?.includes(input)}
      />
    );
  }

  const { value, onChange } = props as SingleProps;
  return (
    <Select
      showSearch
      style={style || { width: 180 }}
      placeholder={placeholder || '选择疾病'}
      value={value || undefined}
      onChange={(v) => onChange(v || '')}
      allowClear={allowClear}
      options={DISEASES.map((d) => ({ value: d.key, label: d.name_cn }))}
      filterOption={(input, option) => (option?.label as string)?.includes(input)}
    />
  );
};

export default DiseaseSelector;
