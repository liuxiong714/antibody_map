import React from 'react';
import { Select, Space } from 'antd';
import { BgColorsOutlined } from '@ant-design/icons';
import { useTheme, THEME_OPTIONS } from '../theme';

/** 头部主题切换器：默认主题（现有外观）/ 候选主题（登录页配色新设计） */
const ThemeSwitcher: React.FC = () => {
  const { theme, setTheme } = useTheme();

  return (
    <Space size={4}>
      <BgColorsOutlined style={{ color: '#999' }} />
      <Select
        value={theme}
        onChange={setTheme}
        size="small"
        style={{ width: 110 }}
        options={THEME_OPTIONS}
      />
    </Space>
  );
};

export default ThemeSwitcher;
