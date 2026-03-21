# 聊天区域等待回复时忽略特定消息类型

## 问题描述

在聊天区域发送消息后，等待AI回复时，WebSocket 会推送 `review_display_view` 和 `completion_request` 类型的消息，这些消息会被渲染到聊天区域。

用户希望在"发送消息后等待回复"这个特定场景下，不渲染这些数据，与其他情况（如上传文件后、历史会话加载等）区分开来。

## 根本原因

`completion_request` 消息使用独立的 `onCompletionRequest` 回调处理，而不是通过 `onProgress` 回调。之前只在 `onProgress` 回调中添加了检查逻辑，但遗漏了 `onCompletionRequest` 回调。

## 解决方案

### 1. 添加等待回复状态标记

在 `src/store/useAppStore.ts` 中添加新的状态：

```typescript
isWaitingForReply: boolean  // 是否正在等待AI回复（发送消息后）
```

### 2. 在发送消息时设置标记

在 `src/components/ChatInterface.tsx` 的 `handleSendMessage` 函数中：

- 发送消息前：`setIsWaitingForReply(true)`
- 收到回复后：延迟 2 秒清除标记 `setTimeout(() => setIsWaitingForReply(false), 2000)`
- 发生错误时：延迟 2 秒清除标记

**为什么要延迟清除？**

因为 WebSocket 的 `review_display_view` 和 `completion_request` 消息可能在 HTTP API 响应之后才到达，且这两条消息会一前一后出现。通过延迟 2 秒清除标记，可以确保在这段时间内到达的所有 WebSocket 消息都会被忽略。

### 3. 在 WebSocket 处理中检查标记

在以下文件的 WebSocket 消息处理逻辑中，添加检查：

- `src/components/Sidebar.tsx`
- `src/components/FileUpload.tsx`
- `src/components/HistorySessions.tsx`

#### 在 `onProgress` 回调中检查（处理 `review_display_view`）：
```typescript
// 如果正在等待AI回复，且收到的是 review_display_view 或 completion_request，则忽略
const isWaitingForReply = useAppStore.getState().isWaitingForReply
if (isWaitingForReply && (isReviewDisplayView || isCompletionRequest)) {
  console.log('⏭️ 正在等待AI回复，忽略 review_display_view 或 completion_request 消息')
  return
}
```

#### 在 `onCompletionRequest` 回调中检查（处理 `completion_request`）：
```typescript
// 如果正在等待AI回复，则忽略
const isWaitingForReply = useAppStore.getState().isWaitingForReply
if (isWaitingForReply) {
  console.log('⏭️ 正在等待AI回复，忽略 completion_request 消息')
  return
}
```

**重要**：`completion_request` 消息使用独立的 `onCompletionRequest` 回调，需要单独添加检查逻辑。

## 修改的文件

1. `src/store/useAppStore.ts` - 添加状态和 setter
2. `src/components/ChatInterface.tsx` - 在发送消息时设置/延迟清除标记
3. `src/components/Sidebar.tsx` - 在 `onProgress` 和 `onCompletionRequest` 回调中检查标记
4. `src/components/FileUpload.tsx` - 在 `onProgress` 和 `onCompletionRequest` 回调中检查标记
5. `src/components/HistorySessions.tsx` - 在 `onProgress` 和 `onCompletionRequest` 回调中检查标记
6. `src/services/historyService.ts` - 在 `convertToAppMessages` 函数中过滤历史消息

## 工作流程

1. 用户发送消息 → `isWaitingForReply = true`
2. WebSocket 推送 `review_display_view` → 在 `onProgress` 回调中检测到 `isWaitingForReply = true` → 忽略消息
3. WebSocket 推送 `completion_request` → 在 `onCompletionRequest` 回调中检测到 `isWaitingForReply = true` → 忽略消息
4. AI 回复完成 → 延迟 2 秒后 `isWaitingForReply = false`
5. 后续的 WebSocket 消息正常处理

## 时序说明

```
用户发送消息 (t=0)
    ↓
设置 isWaitingForReply = true
    ↓
HTTP API 请求发送
    ↓
WebSocket 推送 review_display_view (t=200ms, 被忽略)
    ↓
WebSocket 推送 completion_request (t=400ms, 被忽略)
    ↓
HTTP API 响应返回 (t=600ms)
    ↓
添加 AI 消息到界面
    ↓
2 秒后清除 isWaitingForReply = false (t=2600ms)
    ↓
后续 WebSocket 消息正常处理
```

**注意**：延迟时间设置为 2 秒，可以确保即使 WebSocket 消息在 HTTP 响应之后才到达，也能被正确忽略。

## 测试场景

- ✅ 发送消息后等待回复时，不渲染 `review_display_view` 和 `completion_request`（实时 WebSocket）
- ✅ 上传文件后，正常渲染这些消息（实时 WebSocket）
- ✅ 加载历史会话时，智能过滤：
  - 用户消息和 AI 回复之间的 `review_display_view` 和 `completion_request` 不渲染
  - 其他位置的这些消息正常渲染（如上传文件后的初始识别）
- ✅ 确认操作后，正常渲染这些消息（实时 WebSocket）
- ✅ WebSocket 消息在 API 响应之后到达时，也能被正确忽略（通过延迟清除实现）

## 历史消息过滤

在 `src/services/historyService.ts` 的 `convertToAppMessages` 函数中，添加了智能过滤逻辑：

### 过滤规则

1. **过滤所有 `system_message` 类型的消息**
   - 这些是系统提示消息，如"已自动重新加载历史数据"
   - 无论位置，都会被过滤掉

2. **智能过滤 `review_display_view` 和 `completion_request`**
   - 只过滤掉**用户消息**（`role: user`, `action: modify`）和**AI回复**（`role: assistant`, `action: modify_response`）之间的这些消息
   - 其他位置的这些消息会正常渲染，例如：
     - 上传文件后的初始特征识别过程
     - 确认操作后的数据刷新
     - 其他非对话场景的消息

### 实现逻辑

```typescript
// 1. 过滤所有 system_message
if (isSystemMessage) {
  return false  // 直接过滤
}

// 2. 智能过滤 review_display_view 和 completion_request
if (isReviewDisplayView || isCompletionRequest) {
  // 查找前一条非 review/completion/system_message 消息
  // 查找后一条非 review/completion/system_message 消息
  
  // 如果前一条是用户消息（action: modify），后一条是AI回复（action: modify_response）
  // 则过滤掉这条消息
  if (prevMsg?.role === 'user' && prevMsg?.metadata?.action === 'modify' &&
      nextMsg?.role === 'assistant' && nextMsg?.metadata?.action === 'modify_response') {
    return false  // 过滤掉
  }
}

return true  // 保留其他消息
```

这样可以确保：
- 所有系统提示消息都不显示
- 用户发送消息后，中间的状态消息不会显示
- 其他场景的状态消息正常显示
