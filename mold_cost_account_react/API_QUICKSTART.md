# API 快速开始

## 简介

CodeWhisper 提供 REST API 接口，让你可以通过 HTTP 请求调用语音转文字功能，方便集成到其他应用中。

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn python-multipart requests
```

### 2. 启动 API 服务器

```bash
# 基本启动（默认端口 8000）
python api_server.py

# 指定端口
python api_server.py --port 8080

# 开发模式（代码修改自动重载）
python api_server.py --reload

# 预加载大模型
python api_server.py --model medium
```

启动后会显示：
```
🚀 启动 CodeWhisper API Server
📦 预加载模型: small
🌐 服务器地址: http://0.0.0.0:8000
📖 API 文档: http://0.0.0.0:8000/docs
🔧 交互式文档: http://0.0.0.0:8000/redoc
```

### 3. 访问交互式文档

打开浏览器访问 http://localhost:8000/docs，可以直接在网页上测试 API。

## 基本使用

### Python 调用示例

```python
import requests

# 转录音频文件
with open("audio.wav", "rb") as f:
    files = {"file": f}
    data = {
        "model": "small",
        "language": "zh",
        "fix_terms": True
    }
    
    response = requests.post(
        "http://localhost:8000/api/transcribe",
        files=files,
        data=data
    )
    
    result = response.json()
    print(f"转录结果: {result['text']}")
    print(f"修正次数: {result['corrections']['count']}")
```

### cURL 调用示例

```bash
curl -X POST "http://localhost:8000/api/transcribe" \
  -F "file=@audio.wav" \
  -F "model=small" \
  -F "language=zh" \
  -F "fix_terms=true"
```

### JavaScript 调用示例

```javascript
const formData = new FormData();
formData.append('file', audioFile);
formData.append('model', 'small');
formData.append('language', 'zh');

fetch('http://localhost:8000/api/transcribe', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => {
  console.log('转录结果:', data.text);
  console.log('修正次数:', data.corrections.count);
});
```

## 使用客户端库

我们提供了 Python 客户端库，使用更简单：

```python
from examples.api_client import CodeWhisperClient

# 创建客户端
client = CodeWhisperClient("http://localhost:8000")

# 健康检查
health = client.health_check()
print(f"状态: {health['status']}")

# 转录文件
result = client.transcribe_file(
    "audio.wav",
    model="small",
    language="zh",
    verbose=True
)

print(f"转录结果: {result['text']}")
print(f"语言: {result['language']}")
print(f"修正次数: {result['corrections']['count']}")

# 查看修正详情
for correction in result['corrections']['details']:
    print(f"  {correction['wrong']} → {correction['correct']}")
```

## 实时语音输入

CodeWhisper API 支持直接输入语音数据，无需先保存为文件！

### 1. Base64 流式接口 ⭐ 推荐用于简单场景

**POST /api/transcribe/stream**

直接发送 Base64 编码的音频数据。

**Python 示例：**
```python
import requests
import base64

# 读取音频数据
with open("audio.wav", "rb") as f:
    audio_bytes = f.read()

# 编码为 Base64
audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

# 发送请求
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

**JavaScript 示例：**
```javascript
// 从麦克风录音
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => {
    const mediaRecorder = new MediaRecorder(stream);
    const audioChunks = [];
    
    mediaRecorder.ondataavailable = (event) => {
      audioChunks.push(event.data);
    };
    
    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
      const reader = new FileReader();
      
      reader.onloadend = async () => {
        const base64Audio = reader.result.split(',')[1];
        
        const formData = new FormData();
        formData.append('audio_data', base64Audio);
        formData.append('model', 'small');
        
        const response = await fetch('http://localhost:8000/api/transcribe/stream', {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        console.log(result.text);
      };
      
      reader.readAsDataURL(audioBlob);
    };
    
    mediaRecorder.start();
    setTimeout(() => mediaRecorder.stop(), 5000);
  });
```

**特点：**
- ✅ 简单易用
- ✅ 一次性转录
- ✅ 兼容性好
- ✅ 适合网页应用

### 2. WebSocket 接口 ⭐⭐ 推荐用于实时场景

**WS /ws/transcribe**

使用 WebSocket 进行双向通信，支持分块发送音频数据。

**Python 示例：**
```python
import asyncio
import websockets
import json
import base64

async def transcribe_realtime():
    uri = "ws://localhost:8000/ws/transcribe"
    
    async with websockets.connect(uri) as websocket:
        # 开始会话
        await websocket.send(json.dumps({
            "action": "start",
            "model": "small",
            "language": "zh"
        }))
        
        response = await websocket.recv()
        print(json.loads(response)['message'])
        
        # 发送音频数据（分块）
        with open("audio.wav", "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                
                encoded = base64.b64encode(chunk).decode('utf-8')
                await websocket.send(json.dumps({
                    "action": "audio",
                    "data": encoded
                }))
                
                response = await websocket.recv()
                print(json.loads(response)['message'])
        
        # 结束并获取结果
        await websocket.send(json.dumps({
            "action": "end"
        }))
        
        response = await websocket.recv()
        result = json.loads(response)
        print(f"转录结果: {result['text']}")

asyncio.run(transcribe_realtime())
```

**协议：**
```json
// 客户端发送
{"action": "start", "model": "small", "language": "zh"}
{"action": "audio", "data": "base64_encoded_audio"}
{"action": "end"}

// 服务器响应
{"type": "status", "message": "会话已开始"}
{"type": "result", "text": "转录结果", "corrections": {...}}
```

**特点：**
- ✅ 真正的实时通信
- ✅ 可以边录边发
- ✅ 支持长时间录音
- ✅ 低延迟
- ✅ 双向通信

### 3. 网页录音示例

我们提供了完整的 HTML 网页示例！

**使用方法：**
1. 启动服务器：`python api_server.py`
2. 在浏览器中打开：`examples/web_recorder.html`
3. 点击"开始录音" → 说话 → 点击"停止录音"
4. 查看转录结果！

**功能特性：**
- 🎤 浏览器内录音
- 🚀 实时转录
- 🔧 术语自动修正
- 📊 修正详情显示
- ⚙️ 模型和语言选择
- 🎨 美观的界面

### 4. 三种方式对比

| 方式 | 延迟 | 复杂度 | 适用场景 |
|------|------|--------|----------|
| 文件上传 | 高 | 低 | 已有音频文件 |
| Base64 流 | 中 | 低 | 网页应用、简单场景 |
| WebSocket | 低 | 中 | 实时对话、长时间录音 |

## 主要 API 端点

### 1. 转录音频文件

**POST /api/transcribe**

上传音频文件进行转录。

**参数：**
- `file`: 音频文件（必需）
- `model`: 模型大小，可选 tiny/base/small/medium/large（默认：small）
- `language`: 语言代码（默认：zh）
- `fix_terms`: 是否修正术语（默认：true）
- `learn`: 是否学习用户习惯（默认：true）
- `verbose`: 是否返回详细信息（默认：false）

**支持的音频格式：** wav, mp3, m4a, flac, ogg, webm

### 2. 从 URL 转录

**POST /api/transcribe/url**

从 URL 下载并转录音频文件。

**参数：**
- `url`: 音频文件 URL（必需）
- `model`: 模型大小（默认：small）
- `language`: 语言代码（默认：zh）
- `fix_terms`: 是否修正术语（默认：true）
- `learn`: 是否学习用户习惯（默认：true）

### 3. 健康检查

**GET /api/health**

检查服务器状态。

### 4. 列出模型

**GET /api/models**

列出支持的模型。

### 5. 获取统计信息

**GET /api/stats**

获取字典和模型统计信息。

## 响应格式

成功响应示例：

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

错误响应示例：

```json
{
  "detail": "不支持的文件格式: .txt"
}
```

## 测试 API

### 使用测试脚本

**Linux/Mac:**
```bash
chmod +x examples/test_api.sh
./examples/test_api.sh
```

**Windows:**
```powershell
.\examples\test_api.ps1
```

### 使用 Swagger UI

访问 http://localhost:8000/docs，可以在网页上直接测试所有 API。

## 生产部署

### 使用 Gunicorn

```bash
pip install gunicorn

gunicorn api_server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### 使用 Docker

```bash
docker build -t codewhisper-api .
docker run -p 8000:8000 codewhisper-api
```

## 性能建议

1. **预加载模型**：启动时使用 `--model` 参数预加载模型
2. **多进程部署**：使用 Gunicorn 的多个 worker
3. **GPU 加速**：如果有 GPU，会自动使用 CUDA 加速
4. **限制文件大小**：生产环境应限制上传文件大小

## 安全建议

1. **限制 CORS**：生产环境应限制允许的域名
2. **限制请求频率**：使用 nginx 或 slowapi 限流
3. **使用 HTTPS**：生产环境使用 HTTPS
4. **文件大小限制**：限制上传文件大小（如 50MB）

## 更多信息

详细的 API 文档请参考：[API_DOCUMENTATION.md](API_DOCUMENTATION.md)

## 常见问题

**Q: 首次请求很慢？**  
A: 首次请求需要加载模型，可以使用 `--model` 参数预加载。

**Q: 如何支持更多语言？**  
A: 修改 `language` 参数，Whisper 支持 99 种语言。

**Q: 可以并发处理吗？**  
A: 可以，使用多个 worker 或异步处理。

**Q: 支持实时转录吗？**  
A: 当前版本不支持，需要完整的音频文件。
