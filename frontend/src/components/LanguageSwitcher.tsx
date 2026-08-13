import React from 'react';
import { Select, Space } from 'antd';
import { GlobalOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

const LanguageSwitcher: React.FC = () => {
  const { i18n } = useTranslation();

  const handleChange = (value: string) => {
    i18n.changeLanguage(value);
    localStorage.setItem('app_language', value);
  };

  return (
    <Space size={4}>
      <GlobalOutlined style={{ color: '#999' }} />
      <Select
        value={i18n.language}
        onChange={handleChange}
        size="small"
        style={{ width: 85 }}
        options={[
          { value: 'zh', label: '中文' },
          { value: 'en', label: 'English' },
        ]}
      />
    </Space>
  );
};

export default LanguageSwitcher;