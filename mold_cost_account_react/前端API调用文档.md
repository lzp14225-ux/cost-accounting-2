# CosyVoice 前端 API 调用文档

## 概述

本文档介绍如何在前端（浏览器）中调用 CosyVoice Gradio API 进行文字转语音。

## 服务器地址

- **本地访问**: `http://127.0.0.1:8000`
- **局域网访问**: `http://192.168.1.154:8000`（替换为你的实际 IP）

## API 端点

### 1. 生成音频

**端点**: `/gradio_api/call/generate_audio`

**方法**: POST

**请求格式**:

```javascript
{
  "data": [
    "要合成的文本",           // tts_text
    "预训练音色",             // mode_checkbox_group
    "中文女",                 // sft_dropdown (音色选择)
    "",                      // prompt_text
    null,                    // prompt_wav_upload
    null,                    // prompt_wav_record
    "",                      // instruct_text
    0,                       // seed
    true,                    // stream (流式推理: true/false)
    1.0                      // speed (语速: 0.5-2.0)
  ]
}
```

**响应格式**:

```javascript
{
  "event_id": "uuid-string"  // 用于获取结果的事件 ID
}
```

### 2. 获取生成结果

**端点**: `/gradio_api/call/generate_audio/{event_id}`

**方法**: GET

**响应格式**: Server-Sent Events (SSE) 流

## 完整调用示例

### 基础示例

```javascript
// 配置
const API_BASE_URL = 'http://192.168.1.154:8000';

// 第一步：提交生成请求
async function generateSpeech(text, speaker = '中文女', streamMode = true, speed = 1.0) {
  const response = await fetch(`${API_BASE_URL}/gradio_api/call/generate_audio`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      data: [
        text,              // 要合成的文本
        "预训练音色",       // 模式
        speaker,           // 音色
        "",                // prompt_text
        null,              // prompt_wav_upload
        null,              // prompt_wav_record
        "",                // instruct_text
        0,                 // seed
        streamMode,        // 是否流式
        speed              // 语速
      ]
    })
  });

  const result = await response.json();
  return result.event_id;
}

// 第二步：获取生成结果
async function getAudioResult(eventId) {
  const response = await fetch(`${API_BASE_URL}/gradio_api/call/generate_audio/${eventId}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event: complete')) {
        console.log('生成完成');
      }
      
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.substring(6));
        
        // 检查是否是音频数据
        if (Array.isArray(data) && data[0]?.url) {
          let audioUrl = data[0].url;
          
          // 修复 URL 路径（移除错误的 /gradio_a/ 前缀）
          if (audioUrl.includes('/gradio_a/gradio_api/')) {
            audioUrl = audioUrl.replace('/gradio_a/gradio_api/', '/gradio_api/');
          }
          
          // 确保是完整 URL
          if (!audioUrl.startsWith('http')) {
            audioUrl = `${API_BASE_URL}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
          }
          
          return audioUrl;
        }
      }
    }
  }
}

// 使用示例
async function main() {
  try {
    const eventId = await generateSpeech('你好，这是一个测试。', '中文女', true, 1.0);
    console.log('Event ID:', eventId);
    
    const audioUrl = await getAudioResult(eventId);
    console.log('音频 URL:', audioUrl);
    
    // 播放音频
    const audio = new Audio(audioUrl);
    audio.play();
  } catch (error) {
    console.error('生成失败:', error);
  }
}
```

### 完整的 HTML 示例

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>CosyVoice TTS 示例</title>
</head>
<body>
    <h1>CosyVoice 文字转语音</h1>
    
    <div>
        <label>文本：</label>
        <textarea id="text" rows="4" cols="50">你好，这是一个测试。</textarea>
    </div>
    
    <div>
        <label>音色：</label>
        <select id="speaker">
            <option value="中文女">中文女</option>
            <option value="中文男">中文男</option>
            <option value="日语男">日语男</option>
            <option value="粤语女">粤语女</option>
            <option value="英文女">英文女</option>
            <option value="英文男">英文男</option>
            <option value="韩语女">韩语女</option>
        </select>
    </div>
    
    <div>
        <label>语速：</label>
        <input type="range" id="speed" min="0.5" max="2.0" step="0.1" value="1.0">
        <span id="speedValue">1.0x</span>
    </div>
    
    <div>
        <label>
            <input type="checkbox" id="stream" checked>
            启用流式推理
        </label>
    </div>
    
    <button onclick="generate()">生成语音</button>
    
    <div id="status"></div>
    <audio id="audio" controls style="display:none;"></audio>

    <script>
        const API_BASE_URL = 'http://192.168.1.154:8000';
        
        // 更新语速显示
        document.getElementById('speed').addEventListener('input', (e) => {
            document.getElementById('speedValue').textContent = e.target.value + 'x';
        });
        
        async function generate() {
            const text = document.getElementById('text').value;
            const speaker = document.getElementById('speaker').value;
            const speed = parseFloat(document.getElementById('speed').value);
            const stream = document.getElementById('stream').checked;
            const statusEl = document.getElementById('status');
            const audioEl = document.getElementById('audio');
            
            try {
                statusEl.textContent = '正在生成...';
                
                // 提交请求
                const response = await fetch(`${API_BASE_URL}/gradio_api/call/generate_audio`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        data: [text, "预训练音色", speaker, "", null, null, "", 0, stream, speed]
                    })
                });
                
                const result = await response.json();
                const eventId = result.event_id;
                
                // 获取结果
                const audioUrl = await getResult(eventId);
                
                // 播放音频
                audioEl.src = audioUrl;
                audioEl.style.display = 'block';
                audioEl.play();
                
                statusEl.textContent = '生成成功！';
            } catch (error) {
                statusEl.textContent = '生成失败: ' + error.message;
            }
        }
        
        async function getResult(eventId) {
            const response = await fetch(`${API_BASE_URL}/gradio_api/call/generate_audio/${eventId}`);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.substring(6));
                        
                        if (Array.isArray(data) && data[0]?.url) {
                            let audioUrl = data[0].url;
                            
                            // 修复 URL
                            if (audioUrl.includes('/gradio_a/gradio_api/')) {
                                audioUrl = audioUrl.replace('/gradio_a/gradio_api/', '/gradio_api/');
                            }
                            if (!audioUrl.startsWith('http')) {
                                audioUrl = `${API_BASE_URL}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
                            }
                            
                            return audioUrl;
                        }
                    }
                }
            }
            
            throw new Error('未获取到音频');
        }
    </script>
</body>
</html>
```

## 参数说明

### 音色选项 (sft_dropdown)

- `中文女` - 中文女声
- `中文男` - 中文男声
- `日语男` - 日语男声
- `粤语女` - 粤语女声
- `英文女` - 英文女声
- `英文男` - 英文男声
- `韩语女` - 韩语女声

### 语速 (speed)

- 范围: `0.5` - `2.0`
- 默认: `1.0`
- `0.5` = 慢速
- `1.0` = 正常速度
- `2.0` = 快速

### 流式推理 (stream)

- `true` - 启用流式推理（返回 m3u8 格式，支持渐进式播放）
- `false` - 非流式推理（返回完整 WAV 文件）

## 常见问题

### 1. CORS 跨域问题

如果从 `file://` 协议打开 HTML 文件，会遇到 CORS 错误。解决方案：

**方法 1**: 使用 HTTP 服务器

```bash
# Python 3
python -m http.server 8080

# 然后访问 http://localhost:8080/your-file.html
```

**方法 2**: 使用提供的 `start_client.py`

```bash
python start_client.py
# 访问 http://localhost:8080/tts_client.html
```

### 2. URL 路径错误

如果音频 URL 包含 `/gradio_a/gradio_api/`，需要修复为 `/gradio_api/`：

```javascript
if (audioUrl.includes('/gradio_a/gradio_api/')) {
    audioUrl = audioUrl.replace('/gradio_a/gradio_api/', '/gradio_api/');
}
```

### 3. 音频格式支持

- **流式模式**: 返回 m3u8 格式（HLS），需要浏览器支持
- **非流式模式**: 返回 WAV 格式，所有浏览器都支持

推荐使用支持 HLS 的现代浏览器（Chrome、Edge、Safari）。

### 4. 局域网访问

确保：
1. Gradio 服务器监听 `0.0.0.0`（默认配置）
2. 防火墙允许 8000 端口
3. 使用局域网 IP 地址而不是 `127.0.0.1`

## 性能优化

### 1. 使用流式推理

流式推理可以更快地开始播放音频：

```javascript
const streamMode = true;  // 推荐
```

### 2. 预加载音频

```javascript
const audio = new Audio();
audio.preload = 'auto';
audio.src = audioUrl;
```

### 3. 错误处理

```javascript
audio.onerror = (e) => {
    console.error('音频加载失败:', e);
    // 重试或提示用户
};

audio.onloadeddata = () => {
    console.log('音频加载成功');
};
```

## 完整工作流程

```
1. 用户输入文本
   ↓
2. 前端发送 POST 请求到 /gradio_api/call/generate_audio
   ↓
3. 服务器返回 event_id
   ↓
4. 前端使用 event_id 轮询 /gradio_api/call/generate_audio/{event_id}
   ↓
5. 服务器通过 SSE 流返回生成进度和结果
   ↓
6. 前端解析 SSE 数据，提取音频 URL
   ↓
7. 修复 URL 路径（如果需要）
   ↓
8. 使用 <audio> 标签播放音频
```

## 示例项目

完整的示例项目已包含在仓库中：

- `tts_client.html` - 完整的前端客户端
- `start_client.py` - HTTP 服务器
- `API_DOCUMENTATION.md` - 详细的 API 文档

## 技术支持

如有问题，请查看：
- `API_DOCUMENTATION.md` - 完整 API 文档
- `FAQ.md` - 常见问题解答
- 浏览器控制台日志 - 调试信息
