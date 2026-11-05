# 前端开源组件

- [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui)：MIT；实际使用 @assistant-ui/react 的 ExternalStoreRuntime、Thread、Message 与 Composer primitives。
- React / React DOM：MIT。
- react-markdown / remark-gfm：MIT；不启用原始 HTML。
- lucide-react：ISC；界面图标。

所有依赖版本锁定在 package-lock.json，没有依赖 assistant-cloud 或商业托管服务。现有 Python 后端继续持有任务和模型状态，浏览器不保存模型密钥。建议 Node.js 24 LTS；服务器只接收静态构建产物，无需 Node。
