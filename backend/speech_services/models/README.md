# Whisper 模型缓存目录

此目录用于存放 Whisper 语音识别模型文件。

## 目录说明

模型文件会自动下载到此目录，无需手动操作。

**首次启动时**：
- 系统会自动从 Azure CDN 下载模型
- 下载完成后缓存到此目录
- 下次启动直接使用缓存，无需重新下载

## 模型文件

| 文件名 | 大小 | 说明 |
|--------|------|------|
| `tiny.pt` | ~75 MB | 最小模型，速度最快 |
| `base.pt` | ~142 MB | 基础模型 |
| `small.pt` | ~466 MB | 推荐模型 ✅ |
| `medium.pt` | ~1.5 GB | 中等模型 |
| `large-v3.pt` | ~2.9 GB | 最大模型 |

## 当前配置

**默认模型**: small

**缓存位置**: `mold_cost_/speech_services/models/`

**优点**:
- ✅ 模型文件在项目目录中，便于管理
- ✅ 团队成员可以共享模型文件
- ✅ 不依赖系统缓存目录
- ✅ 便于备份和迁移

## 手动下载模型

如果自动下载失败，可以手动下载：

### 1. 下载模型文件

访问 Azure CDN 下载地址：

**small 模型**:
```
https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt
```

**其他模型**:
- tiny: https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt
- base: https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt
- medium: https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt

### 2. 放到此目录

将下载的 `.pt` 文件放到此目录：
```
mold_cost_/speech_services/models/small.pt
```

### 3. 重启服务

```bash
cd mold_cost_\speech_services
start_speech.bat
```

## 从系统缓存复制

如果已经在系统缓存中下载过模型，可以直接复制：

**Windows**:
```bash
# 复制 small 模型
copy "%USERPROFILE%\.cache\whisper\small.pt" "mold_cost_\speech_services\models\small.pt"
```

**Linux/Mac**:
```bash
# 复制 small 模型
cp ~/.cache/whisper/small.pt mold_cost_/speech_services/models/small.pt
```

## 团队共享

### 方法 1: 网络共享

将模型文件放到团队共享目录：
```
\\server\shared\whisper_models\small.pt
```

### 方法 2: 内网服务器

搭建内网文件服务器，提供模型下载。

### 方法 3: Git LFS

如果使用 Git LFS，可以将模型文件纳入版本控制：
```bash
git lfs track "*.pt"
git add .gitattributes
git add models/small.pt
git commit -m "Add Whisper model"
```

**注意**: 模型文件很大，不建议直接提交到普通 Git 仓库。

## 磁盘空间

### 单个模型

| 模型 | 磁盘占用 |
|------|---------|
| tiny | ~75 MB |
| base | ~142 MB |
| small | ~466 MB |
| medium | ~1.5 GB |
| large | ~2.9 GB |

### 多个模型

如果需要多个模型，确保有足够的磁盘空间：
- tiny + base + small: ~683 MB
- small + medium: ~2 GB
- 全部模型: ~5 GB

## 清理模型

如果需要清理不用的模型：

```bash
# 删除特定模型
del mold_cost_\speech_services\models\medium.pt

# 清空所有模型（保留 README）
del mold_cost_\speech_services\models\*.pt
```

## 验证模型

启动服务后，检查日志：

```
📦 Whisper 模型: small
📁 模型缓存目录: D:\...\mold_cost_\speech_services\models
✅ 模型加载完成
```

或访问 API：
```bash
curl http://192.168.1.143:8888/api/health
```

响应：
```json
{
  "status": "healthy",
  "loaded_models": ["small"],
  "device": "cpu"
}
```

## 故障排查

### 问题 1: 模型下载失败

**解决**:
1. 检查网络连接
2. 手动下载模型文件
3. 放到此目录

### 问题 2: SHA256 校验失败

**解决**:
```bash
# 删除损坏的文件
del mold_cost_\speech_services\models\small.pt

# 重新启动服务，自动重新下载
start_speech.bat
```

### 问题 3: 权限不足

**解决**:
```bash
# 检查目录权限
icacls mold_cost_\speech_services\models

# 如果需要，修改权限
icacls mold_cost_\speech_services\models /grant Users:F
```

## 备份建议

### 定期备份

```bash
# 备份模型文件
xcopy mold_cost_\speech_services\models\*.pt D:\backup\whisper_models\ /Y
```

### 云备份

将模型文件上传到云存储：
- 阿里云 OSS
- 腾讯云 COS
- 百度网盘
- OneDrive

## 更新日期

2026-03-02
