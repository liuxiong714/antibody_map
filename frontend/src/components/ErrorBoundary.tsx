import React from 'react';
import { Button, Result, Space, Typography } from 'antd';
import { ReloadOutlined, HomeOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

interface Props {
  children: React.ReactNode;
  /** 是否为页面级错误边界（显示返回首页按钮） */
  page?: boolean;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

interface ErrorFallbackProps {
  error: Error | null;
  page?: boolean;
  onReset: () => void;
}

const ErrorFallbackContent: React.FC<ErrorFallbackProps> = ({ error, page, onReset }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleReset = () => {
    onReset();
  };

  const handleGoHome = () => {
    onReset();
    navigate('/');
  };

  return (
    <Result
      status="error"
      title={t('error.title', '页面出现异常')}
      subTitle={t('error.subtitle', '很抱歉，页面遇到了一个意外错误。您可以尝试刷新或重试。')}
      extra={
        <Space>
          <Button type="primary" icon={<ReloadOutlined />} onClick={handleReset}>
            {t('error.retry', '重试')}
          </Button>
          {page && (
            <Button icon={<HomeOutlined />} onClick={handleGoHome}>
              {t('error.backHome', '返回首页')}
            </Button>
          )}
        </Space>
      }
    >
      {error && (
        <Typography.Paragraph type="danger" style={{ textAlign: 'left', maxWidth: 480, margin: '0 auto' }}>
          <Typography.Text code>{error.message || 'Unknown error'}</Typography.Text>
        </Typography.Paragraph>
      )}
    </Result>
  );
};

class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <ErrorFallbackContent
          error={this.state.error}
          page={this.props.page}
          onReset={this.handleReset}
        />
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;