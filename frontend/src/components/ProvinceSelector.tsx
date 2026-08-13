import React from 'react';
import { Select } from 'antd';
import { PROVINCES } from '../utils/constants';

interface BaseProps {
  allowClear?: boolean;
  multiple?: boolean;
  placeholder?: string;
  style?: React.CSSProperties;
}

// 单选：value 为 string，onChange 接收 string
interface SingleProps extends BaseProps {
  multiple?: false;
  value: string;
  onChange: (v: string) => void;
}

// 多选：value 为 string[]，onChange 接收 string[]
interface MultipleProps extends BaseProps {
  multiple: true;
  value: string[];
  onChange: (v: string[]) => void;
}

type Props = SingleProps | MultipleProps;

const ProvinceSelector: React.FC<Props> = (props) => {
  const { allowClear = true, placeholder, style } = props;
  const multiple = props.multiple === true;

  if (multiple) {
    const { value, onChange } = props as MultipleProps;
    return (
      <Select
        showSearch
        mode="multiple"
        style={style || { width: 280 }}
        placeholder={placeholder || '选择省份（可多选）'}
        value={value.length > 0 ? value : undefined}
        onChange={(v) => onChange(v || [])}
        allowClear={allowClear}
        maxTagCount="responsive"
        options={PROVINCES.map((p) => ({ value: p, label: p }))}
        filterOption={(input, option) => (option?.label as string)?.includes(input)}
      />
    );
  }

  const { value, onChange } = props as SingleProps;
  return (
    <Select
      showSearch
      style={style || { width: 160 }}
      placeholder={placeholder || '选择省份'}
      value={value || undefined}
      onChange={(v) => onChange(v || '')}
      allowClear={allowClear}
      options={PROVINCES.map((p) => ({ value: p, label: p }))}
      filterOption={(input, option) => (option?.label as string)?.includes(input)}
    />
  );
};

export default ProvinceSelector;
