// 文件用途：前端入口。挂载 React 根组件，设置 Ant Design 主题（主色 #0F5E6E、系统中文字体）与中文语言包。
import React from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles.css';

// Ant Design 主题：主色、圆角、字体都与原型一致
const theme = {
  token: {
    colorPrimary: '#0F5E6E', // 主色
    colorLink: '#0F5E6E', // 链接色
    colorText: '#17212B', // 正文色
    colorBorder: '#A9B5BF', // 输入框边框
    colorBgLayout: '#F2F4F5', // 页面背景
    borderRadius: 8, // 圆角
    fontSize: 14, // 基础字号
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', system-ui, sans-serif", // 系统中文字体
  },
};

// 挂载到 #root
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={theme} button={{ autoInsertSpace: false }}>
      {/* AntApp 提供 message / modal 的上下文 */}
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
