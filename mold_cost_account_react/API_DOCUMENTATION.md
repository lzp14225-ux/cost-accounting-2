# CodeWhisper API 文档

## 概述

CodeWhisper API 提供 REST 接口，让你可以通过 HTTP 请求调用语音转文字功能。

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn python-multipart requests
```

### 2. 启动服务器

```bash
# 基本启动
python api_server.py

# 指定端口
python api_server.py --port 8888

# 开发模式（自动重载）
python api_server.py --reload

# 预加载大模型
python api_server.py --model medium
```

### 3. 访问文档

启动后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API 端点

### 根路径

**GET /**

返回 API 基本信息。

**响应示例：**
```json
{
  "name": "CodeWhisper API",
  "version": "1.0.0",
  "status": "running",
  "endpoints": {
    "transcribe": "/api/transcribe",
    "health": "/api/health",
    "models": "/api/models"
  }
}
```

---

### 健康检查

**GET /api/health**

检查服务器状态。

**响应示例：**
```json
{
  "status": "healthy",
  "loaded_models": ["small"]
}
```

---

### 列出模型

**GET /api/models**

列出支持的模型。

**响应示例：**
```json
{
  "models": ["tiny", "base", "small", "medium", "large"],
  "default": "small",
  "loaded": ["small"]
}
```

---

### 转录音频文件

**POST /api/transcribe**

上传音频文件进行转录。

**请求参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | File | 是 | - | 音频文件 |
| model | string | 否 | small | 模型大小：tiny/base/small/medium/large |
| language | string | 否 | zh | 语言代码 |
| fix_terms | boolean | 否 | true | 是否修正术语 |
| learn | boolean | 否 | true | 是否学习用户习惯 |
| verbose | boolean | 否 | false | 是否返回详细信息 |

**支持的音频格式：**
- WAV (.wav)
- MP3 (.mp3)
- M4A (.m4a)
- FLAC (.flac)
- OGG (.ogg)
- WebM (.webm)

**响应示例：**
```json
{
  "success": true,
  "text": "这个模具需要用慢丝割一刀",
  "language": "zh",
  "corrections": {
    "count": 2,
    "details": [
      {
        "wrong": "磨具",
        "correct": "模具",
        "category": "mold"
      },
      {
        "wrong": "慢思",
        "correct": "慢丝",
        "category": "mold"
      }
    ]
  }
}
```

**cURL 示例：**
```bash
curl -X POST "http://localhost:8000/api/transcribe" \
  -F "file=@audio.wav" \
  -F "model=small" \
  -F "language=zh" \
  -F "fix_terms=true" \
  -F "verbose=true"
```

**Python 示例：**
```python
import requests

with open("audio.wav", "rb") as f:
    files = {"file": f}
    data = {
        "model": "small",
        "language": "zh",
        "fix_terms": True,
        "verbose": True
    }
    
    response = requests.post(
        "http://localhost:8000/api/transcribe",
        files=files,
        data=data
    )
    
    result = response.json()
    print(result["text"])
```

**JavaScript 示例：**
```javascript
const formData = new FormData();
formData.append('file', audioFile);
formData.append('model', 'small');
formData.append('language', 'zh');
formData.append('fix_terms', 'true');

fetch('http://localhost:8000/api/transcribe', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => console.log(data.text));
```

---

### 从 URL 转录

**POST /api/transcribe/url**

从 URL 下载并转录音频文件。

**请求参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| url | string | 是 | - | 音频文件 URL |
| model | string | 否 | small | 模型大小 |
| language | string | 否 | zh | 语言代码 |
| fix_terms | boolean | 否 | true | 是否修正术语 |
| learn | boolean | 否 | true | 是否学习用户习惯 |

**响应示例：**
```json
{
  "success": true,
  "text": "转录的文本内容",
  "language": "zh",
  "corrections": {
    "count": 1,
    "details": [...]
  }
}
```

**cURL 示例：**
```bash
curl -X POST "http://localhost:8000/api/transcribe/url" \
  -F "url=https://example.com/audio.wav" \
  -F "model=small"
```

---

### 获取统计信息

**GET /api/stats**

获取字典和模型统计信息。

**响应示例：**
```json
{
  "loaded_models": ["small"],
  "dict_stats": {
    "total_rules": 316,
    "replacements_made": 0
  },
  "dict_categories": {
    "mold": 45,
    "work_terms": 50,
    "student_terms": 80
  }
}
```

---

## 实时语音输入

CodeWhisper API 支持直接输入语音数据，无需先保存为文件。

### 1. Base64 流式接口

**POST /api/transcribe/stream**

上传 Base64 编码的音频数据进行转录。

**请求参数：**

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| audio_data | string | 是 | - | Base64 编码的音频数据 |
| model | string | 否 | small | 模型大小 |
| language | string | 否 | zh | 语言代码 |
| fix_terms | boolean | 否 | true | 是否修正术语 |
| format | string | 否 | wav | 音频格式 |

**请求示例：**
```bash
curl -X POST "http://localhost:8000/api/transcribe/stream" \
  -F "audio_data=$(base64 -w0 audio.wav)" \
  -F "model=small" \
  -F "language=zh"
```

**Python 示例：**
```python
import requests
import base64

with open("audio.wav", "rb") as f:
    audio_base64 = base64.b64encode(f.read()).decode('utf-8')

response = requests.post(
    "http://localhost:8000/api/transcribe/stream",
    data={
        "audio_data": audio_base64,
        "model": "small",
        "language": "zh"
    }
)

result = response.json()
print(result["text"])
```

### 2. WebSocket 接口

**WS /ws/transcribe**

使用 WebSocket 进行实时双向通信。

**连接流程：**

1. 建立 WebSocket 连接
2. 发送 `start` 消息开始会话
3. 发送 `audio` 消息传输音频数据
4. 发送 `end` 消息结束会话
5. 接收转录结果

**消息格式：**

```json
// 开始会话
{
  "action": "start",
  "model": "small",
  "language": "zh"
}

// 发送音频
{
  "action": "audio",
  "data": "base64_encoded_audio"
}

// 结束会话
{
  "action": "end"
}
```

**服务器响应：**
```json
// 状态消息
{
  "type": "status",
  "message": "会话已开始"
}

// 转录结果
{
  "type": "result",
  "text": "转录结果",
  "language": "zh",
  "corrections": {
    "count": 2,
    "details": [...]
  }
}
```

**Python 示例：**
```python
import asyncio
import websockets
import json
import base64

async def transcribe():
    async with websockets.connect("ws://localhost:8000/ws/transcribe") as ws:
        # 开始会话
        await ws.send(json.dumps({"action": "start", "model": "small"}))
        
        # 发送音频数据
        with open("audio.wav", "rb") as f:
            while chunk := f.read(4096):
                await ws.send(json.dumps({
                    "action": "audio",
                    "data": base64.b64encode(chunk).decode()
                }))
        
        # 结束并获取结果
        await ws.send(json.dumps({"action": "end"}))
        result = json.loads(await ws.recv())
        
        if result["type"] == "result":
            print(result["text"])

asyncio.run(transcribe())
```

### 3. 网页录音示例

我们提供了完整的 HTML 网页示例：`examples/web_recorder.html`

可以直接在浏览器中录音并转录，无需编写代码！

**功能：**
- 🎤 浏览器内录音
- 🚀 实时转录
- 🔧 术语自动修正
- 📊 修正详情显示
- ⚙️ 模型和语言选择

### 4. 三种方式对比

| 方式 | 延迟 | 复杂度 | 适用场景 |
|------|------|--------|----------|
| 文件上传 | 高 | 低 | 已有音频文件 |
| Base64 流 | 中 | 低 | 网页应用、简单场景 |
| WebSocket | 低 | 中 | 实时对话、长时间录音 |

---

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误（如不支持的模型、文件格式等） |
| 500 | 服务器内部错误（如转录失败） |

### 错误示例

**不支持的模型：**
```json
{
  "detail": "不支持的模型: xlarge"
}
```

**不支持的文件格式：**
```json
{
  "detail": "不支持的文件格式: .txt。支持的格式: .wav, .mp3, .m4a, .flac, .ogg, .webm"
}
```

---

## 客户端库

### Python 客户端

使用提供的 Python 客户端：

```python
from examples.api_client import CodeWhisperClient

# 创建客户端
client = CodeWhisperClient("http://localhost:8000")

# 健康检查
health = client.health_check()
print(health)

# 转录文件
result = client.transcribe_file(
    "audio.wav",
    model="small",
    language="zh",
    verbose=True
)
print(result["text"])

# 从 URL 转录
result = client.transcribe_url(
    "https://example.com/audio.wav",
    model="small"
)
print(result["text"])

# 获取统计
stats = client.get_stats()
print(stats)
```

### 其他语言

可以使用任何支持 HTTP 的库调用 API：

- **JavaScript/Node.js**: axios, fetch
- **Java**: OkHttp, HttpClient
- **Go**: net/http
- **PHP**: cURL, Guzzle
- **Ruby**: Net::HTTP, HTTParty

---

## 部署

### 开发环境

```bash
python api_server.py --reload
```

### 生产环境

使用 Gunicorn + Uvicorn workers：

```bash
pip install gunicorn

gunicorn api_server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### Docker 部署

创建 `Dockerfile`：

```dockerfile
FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "api_server.py", "--host", "0.0.0.0"]
```

构建和运行：

```bash
docker build -t codewhisper-api .
docker run -p 8000:8000 codewhisper-api
```

---

## 性能优化

### 1. 模型预加载

启动时预加载模型，避免首次请求延迟：

```bash
python api_server.py --model medium
```

### 2. 多进程部署

使用多个 worker 处理并发请求：

```bash
gunicorn api_server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker
```

### 3. GPU 加速

如果有 GPU，Whisper 会自动使用 CUDA 加速。

### 4. 缓存

对于相同的音频文件，可以实现缓存机制。

---

## 安全建议

### 1. 限制文件大小

在生产环境中限制上传文件大小：

```python
from fastapi import FastAPI, File, UploadFile
from fastapi.exceptions import RequestValidationError

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件太大")
    # ...
```

### 2. 限制请求频率

使用 slowapi 或 nginx 限制请求频率。

### 3. CORS 配置

生产环境应该限制允许的域名：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
```

### 4. HTTPS

生产环境使用 HTTPS：

```bash
uvicorn api_server:app \
  --host 0.0.0.0 \
  --port 443 \
  --ssl-keyfile key.pem \
  --ssl-certfile cert.pem
```

---

## 监控

### 日志

API 会输出请求日志，可以配置日志级别：

```python
import logging

logging.basicConfig(level=logging.INFO)
```

### 健康检查

定期调用 `/api/health` 检查服务状态。

### 指标

可以集成 Prometheus 等监控工具。

---

## 常见问题

### Q: 首次请求很慢？

A: 首次请求需要加载模型，可以使用 `--model` 参数预加载。

### Q: 如何支持更多语言？

A: 修改 `language` 参数，Whisper 支持 99 种语言。

### Q: 如何添加自定义术语？

A: 编辑 `dictionaries/programmer_terms.json` 添加术语。

### Q: 可以并发处理吗？

A: 可以，使用多个 worker 或异步处理。

### Q: 支持实时转录吗？

A: 当前版本不支持，需要完整的音频文件。

---

## 更新日志

### v1.0.0 (2024-02-24)

- 初始版本
- 支持文件上传转录
- 支持 URL 转录
- 术语修正功能
- 自主学习功能

---

## 支持

如有问题，请提交 Issue 或查看文档。
