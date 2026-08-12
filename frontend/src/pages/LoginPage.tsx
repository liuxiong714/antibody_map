import React, { useState } from "react";
import { Form, Input, Button, Checkbox, Divider, message } from "antd";
import {
  UserOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import api from "../services/api";
import "./LoginPage.css";

interface LoginFormValues {
  username: string;
  password: string;
  remember?: boolean;
}

const LoginPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (values: LoginFormValues) => {
    setLoading(true);
    try {
      const res = await api.post("/auth/login", values);
      const { token, username, display_name, is_admin } = res.data;
      if (values.remember) {
        localStorage.setItem("token", token);
        localStorage.setItem("username", display_name || username);
        localStorage.setItem("is_admin", String(is_admin));
      } else {
        sessionStorage.setItem("token", token);
        sessionStorage.setItem("username", display_name || username);
        sessionStorage.setItem("is_admin", String(is_admin));
      }
      message.success("登录成功，欢迎回来");
      navigate("/");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(detail || "登录失败，请检查账号密码");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      {/* ===== 左侧品牌区 ===== */}
      <div className="login-brand">
        {/* 数据点阵背景 */}
        <svg className="brand-dots" viewBox="0 0 600 600" aria-hidden="true">
          <g fill="rgba(255,255,255,0.16)">
            {Array.from({ length: 90 }).map((_, i) => (
              <circle
                key={i}
                cx={(i * 137.5) % 600}
                cy={(i * 89.3) % 600}
                r={i % 7 === 0 ? 2.5 : 1.5}
              />
            ))}
          </g>
        </svg>

        {/* 抗体 Y 形分子结构 */}
        <svg className="brand-antibody" viewBox="0 0 200 160" aria-hidden="true">
          <defs>
            <linearGradient id="abGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#7dd3fc" />
              <stop offset="100%" stopColor="#4f9cf9" />
            </linearGradient>
          </defs>
          {/* 两条重链（Y 形上臂） */}
          <path
            d="M100 78 L58 28 M100 78 L142 28"
            stroke="url(#abGrad)"
            strokeWidth="4"
            strokeLinecap="round"
            fill="none"
            opacity="0.9"
          />
          {/* 铰链区到 Fc 区（Y 形主干） */}
          <path
            d="M100 78 L100 138"
            stroke="url(#abGrad)"
            strokeWidth="4"
            strokeLinecap="round"
            opacity="0.9"
          />
          {/* 两条轻链 */}
          <path
            d="M100 78 L66 108 M100 78 L134 108"
            stroke="url(#abGrad)"
            strokeWidth="2.5"
            strokeLinecap="round"
            opacity="0.6"
          />
          {/* 抗原结合位点圆点 */}
          <circle cx="52" cy="22" r="7" fill="none" stroke="#38bdf8" strokeWidth="2" />
          <circle cx="148" cy="22" r="7" fill="none" stroke="#38bdf8" strokeWidth="2" />
          <circle cx="52" cy="22" r="2.5" fill="#38bdf8" />
          <circle cx="148" cy="22" r="2.5" fill="#38bdf8" />
        </svg>

        <div className="brand-text">
          <h1 className="brand-title">
            Antibody<span>Map</span>
          </h1>
          <p className="brand-slogan">
            血清抗体流行病学数据可视化与分析平台
          </p>
          <ul className="brand-features">
            <li>文献智能提取 · 精确字符溯源</li>
            <li>交互式免疫地图 · 多维分析</li>
            <li>AI 报告生成 · 策略研判</li>
          </ul>
        </div>
      </div>

      {/* ===== 右侧登录区 ===== */}
      <div className="login-panel">
        <div className="login-card">
          <div className="login-header">
            <div className="login-logo">AM</div>
            <h2>欢迎登录</h2>
            <p>请输入您的账号信息进入科研工作台</p>
          </div>

          <Form<LoginFormValues>
            name="login"
            size="large"
            initialValues={{ remember: true }}
            onFinish={handleLogin}
            requiredMark={false}
          >
            <Form.Item
              name="username"
              rules={[
                { required: true, message: "请输入用户名或邮箱" },
                { min: 3, message: "用户名至少 3 个字符" },
              ]}
            >
              <Input
                prefix={<UserOutlined className="input-icon" />}
                placeholder="用户名 / 邮箱"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined className="input-icon" />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>

            <div className="login-options">
              <Form.Item name="remember" valuePropName="checked" noStyle>
                <Checkbox>记住我</Checkbox>
              </Form.Item>
              <a className="login-link" href="#forgot">
                忘记密码？
              </a>
            </div>

            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                icon={loading ? <LoadingOutlined /> : undefined}
                className="login-submit"
              >
                {loading ? "正在登录…" : "登 录"}
              </Button>
            </Form.Item>
          </Form>

          <Divider plain className="login-divider">
            <span className="divider-text">安全提示</span>
          </Divider>

          <div className="login-security">
            <SafetyCertificateOutlined />
            <span>数据加密传输 · 仅限授权人员访问</span>
          </div>
        </div>

        <div className="login-footer">
          © 2026 免疫规划实验室 · Antibody Map
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
