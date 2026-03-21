# 模具成本核算系统前端

基于React + TypeScript + Ant Design构建的现代化模具成本核算系统前端界面，采用ChatGPT风格的对话式交互设计。

## 🚀 功能特性

### 核心功能
- 🤖 **智能对话界面** - ChatGPT风格的AI助手交互
- 📄 **CAD文件上传** - 支持DWG、PRT格式文件拖拽上传
- 🔍 **实时进度跟踪** - WebSocket实时推送任务处理进度
- 📊 **任务管理** - 完整的任务列表、状态跟踪和历史记录
- ⚙️ **系统设置** - 灵活的参数配置和个性化设置

### 技术特性
- 📱 **响应式设计** - 适配桌面和移动设备
- 🎨 **现代化UI** - 基于Ant Design 5.x的精美界面
- 🔄 **状态管理** - 使用Zustand进行轻量级状态管理
- 🌐 **实时通信** - Socket.IO实现双向实时通信
- 📦 **模块化架构** - 清晰的组件和服务分层

## 🛠️ 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **UI组件**: Ant Design 5.x
- **状态管理**: Zustand
- **路由**: React Router 6
- **HTTP客户端**: Axios
- **实时通信**: Socket.IO Client
- **样式**: CSS + Ant Design主题
- **图标**: Ant Design Icons

## 📦 安装和运行

### 环境要求
- Node.js >= 16.0.0
- npm >= 8.0.0 或 yarn >= 1.22.0

### 安装依赖
```bash
npm install
# 或
yarn install
```

### 开发模式
```bash
npm run dev
# 或
yarn dev
```

访问 http://localhost:3000

### 构建生产版本
```bash
npm run build
# 或
yarn build
```

### 预览生产版本
```bash
npm run preview
# 或
yarn preview
```

## 🏗️ 项目结构

```
src/
├── components/          # React组件
│   ├── ChatInterface.tsx      # 聊天界面主组件
│   ├── MessageList.tsx        # 消息列表组件
│   ├── FileUpload.tsx         # 文件上传组件
│   ├── ProgressIndicator.tsx  # 进度指示器
│   ├── InteractionCards.tsx   # 交互卡片组件
│   ├── JobList.tsx           # 任务列表组件
│   ├── Settings.tsx          # 设置页面
│   └── Sidebar.tsx           # 侧边栏组件
├── services/           # API服务层
│   ├── api.ts                # Axios配置和拦截器
│   ├── chatService.ts        # 聊天相关API
│   ├── fileService.ts        # 文件上传API
│   ├── jobService.ts         # 任务管理API
│   └── websocketService.ts   # WebSocket服务
├── store/              # 状态管理
│   └── useAppStore.ts        # Zustand状态store
├── utils/              # 工具函数
│   └── mockData.ts           # 模拟数据
├── App.tsx             # 应用主组件
├── main.tsx           # 应用入口
└── index.css          # 全局样式
```

## 🎨 界面设计

### 主要界面
1. **聊天界面** - 类似ChatGPT的对话式交互
2. **任务列表** - 显示所有成本核算任务的状态和进度
3. **系统设置** - 配置上传限制、AI参数等

### 设计特点
- 采用ChatGPT的界面风格和交互模式
- 清爽的白色背景配合绿色主题色
- 流畅的动画效果和过渡
- 直观的文件拖拽上传体验
- 实时的进度反馈和状态更新

## 🔧 核心功能说明

### 1. 智能对话
- 支持自然语言交互
- 实时打字效果显示
- 支持Markdown格式消息
- 代码高亮显示

### 2. 文件上传
- 拖拽上传支持
- 多文件同时上传
- 实时上传进度显示
- 文件格式和大小验证
- 自动病毒扫描

### 3. 任务管理
- 任务状态实时更新
- 进度条可视化显示
- 任务历史记录
- 报表下载功能
- 错误处理和重试

### 4. 交互卡片
- 参数缺失提醒
- 表单输入验证
- 多种输入组件支持
- 用户确认和重试选项

## 🔌 API集成

### 后端接口
- `POST /api/v1/jobs/upload` - 文件上传
- `POST /api/v1/chat/message` - 发送消息
- `POST /api/v1/chat/interaction` - 提交交互
- `GET /api/v1/jobs` - 获取任务列表
- `GET /api/v1/jobs/{id}` - 获取任务详情

### WebSocket事件
- `job_status` - 任务状态更新
- `need_user_input` - 需要用户输入
- `ai_message` - AI响应消息
- `progress_update` - 进度更新
- `job_completed` - 任务完成
- `job_failed` - 任务失败

## 🎯 开发说明

### 模拟数据
当前版本使用模拟数据进行演示，包括：
- 模拟文件上传过程
- 模拟AI对话响应
- 模拟任务进度更新
- 模拟交互卡片

### 真实API集成
要连接真实后端API，需要：
1. 更新 `src/services/` 中的API调用
2. 配置正确的后端服务地址
3. 实现WebSocket连接
4. 处理认证和权限

### 自定义配置
可以通过以下方式自定义：
- 修改 `src/main.tsx` 中的主题配置
- 更新 `src/index.css` 中的样式变量
- 调整 `vite.config.ts` 中的代理设置

## 📝 开发计划

### 已完成功能
- ✅ 基础界面框架
- ✅ 聊天对话界面
- ✅ 文件上传功能
- ✅ 任务列表管理
- ✅ 进度跟踪显示
- ✅ 交互卡片组件
- ✅ 系统设置页面
- ✅ 响应式设计

### 待开发功能
- 🔄 用户认证登录
- 🔄 权限管理系统
- 🔄 报表预览功能
- 🔄 数据可视化图表
- 🔄 多语言支持
- 🔄 离线模式支持
- 🔄 PWA功能

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 联系方式

如有问题或建议，请通过以下方式联系：
- 项目Issues: [GitHub Issues](https://github.com/your-repo/issues)
- 邮箱: your-email@example.com

---

**注意**: 这是一个演示版本，使用了模拟数据。在生产环境中使用前，请确保正确配置后端API和数据库连接。