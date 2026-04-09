# 音频文件暂存目录

此目录用于暂存上传的音频文件，方便调试和分析。

## 目录说明

- 所有通过 `/api/transcribe` 接口上传的音频文件都会自动保存到此目录
- 文件命名格式：`{时间戳}_{原始文件名}`
- 例如：`20260302_110530_123456_recording.webm`

## 文件管理

### 查看暂存文件列表

```bash
curl http://192.168.1.152:8888/api/audio/list
```

返回示例：
```json
{
  "total_count": 5,
  "files": [
    {
      "filename": "20260302_110530_123456_recording.webm",
      "size": 81440,
      "size_kb": 79.53,
      "created_at": "2026-03-02T11:05:30",
      "modified_at": "2026-03-02T11:05:30"
    }
  ]
}
```

### 清理旧文件

清理24小时前的文件：
```bash
curl -X DELETE "http://192.168.1.152:8888/api/audio/clean" \
  -F "older_than_hours=24"
```

清理1小时前的文件：
```bash
curl -X DELETE "http://192.168.1.152:8888/api/audio/clean" \
  -F "older_than_hours=1"
```

### 手动清理

```bash
# Windows
Remove-Item mold_cost_\speech_services\audio\* -Exclude .gitignore,README.md

# Linux/Mac
rm -f mold_cost_/speech_services/audio/* && git checkout mold_cost_/speech_services/audio/.gitignore
```

## 注意事项

1. **磁盘空间**：定期清理旧文件，避免占用过多磁盘空间
2. **隐私保护**：音频文件可能包含敏感信息，注意保护
3. **Git 忽略**：此目录已配置 `.gitignore`，音频文件不会被提交到 Git
4. **自动清理**：建议设置定时任务，自动清理旧文件

## 统计信息

查看存储统计：
```bash
curl http://192.168.1.152:8888/api/stats
```

返回示例：
```json
{
  "audio_storage": {
    "directory": "speech_services/audio",
    "file_count": 5,
    "total_size": 407200,
    "total_size_mb": 0.39
  }
}
```

## 调试用途

暂存的音频文件可用于：
- 分析识别失败的原因
- 测试不同的模型参数
- 改进语音识别准确率
- 训练自定义模型
- 问题复现和调试

## 文件格式

支持的音频格式：
- `.wav` - 无损音频
- `.mp3` - 压缩音频
- `.m4a` - Apple 音频
- `.flac` - 无损压缩
- `.ogg` - Ogg Vorbis
- `.webm` - WebM 音频（浏览器录音常用）
