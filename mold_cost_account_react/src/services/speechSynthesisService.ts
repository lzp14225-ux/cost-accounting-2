// 音色配置 - CosyVoice
import config from '../config/env'

export const VOICE_TYPES = {
  FEMALE: '中文女',
  MALE: '中文男',
} as const;

export type VoiceType = typeof VOICE_TYPES[keyof typeof VOICE_TYPES];

// 音色显示名称
export const VOICE_TYPE_NAMES: Record<VoiceType, string> = {
  [VOICE_TYPES.FEMALE]: '中文女',
  [VOICE_TYPES.MALE]: '中文男',
};

// 本地存储键
const VOICE_TYPE_STORAGE_KEY = 'tts_voice_type';

// CosyVoice TTS 配置
const TTS_BASE_URL = config.TTS_BASE_URL;


interface SpeechSynthesisCallbacks {
  onStart?: () => void;
  onAudioData?: (data: ArrayBuffer) => void;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export class SpeechSynthesisService {
  private audioElement: HTMLAudioElement | null = null;
  private isPlaying = false;
  private currentVoiceType: VoiceType = VOICE_TYPES.FEMALE;
  private callbacks: SpeechSynthesisCallbacks = {};
  private abortController: AbortController | null = null;

  constructor() {
    // 从 localStorage 加载音色设置
    this.loadVoiceType();
  }

  /**
   * 从 localStorage 加载音色设置
   */
  private loadVoiceType(): void {
    try {
      const savedVoiceType = localStorage.getItem(VOICE_TYPE_STORAGE_KEY);
      if (savedVoiceType && Object.values(VOICE_TYPES).includes(savedVoiceType as VoiceType)) {
        this.currentVoiceType = savedVoiceType as VoiceType;
      }
    } catch (error) {
      console.error('加载音色设置失败:', error);
    }
  }

  /**
   * 设置音色
   */
  setVoiceType(voiceType: VoiceType): void {
    console.log('🎵 设置音色:', voiceType);
    this.currentVoiceType = voiceType;
    
    try {
      localStorage.setItem(VOICE_TYPE_STORAGE_KEY, voiceType);
    } catch (error) {
      console.error('保存音色设置失败:', error);
    }
  }

  /**
   * 获取当前音色
   */
  getVoiceType(): VoiceType {
    return this.currentVoiceType;
  }

  /**
   * 检查 TTS 服务是否可用
   */
  async checkServiceAvailability(): Promise<boolean> {
    try {
      console.log('🔍 检查 TTS 服务可用性:', TTS_BASE_URL);
      const response = await fetch(`${TTS_BASE_URL}/`, {
        method: 'HEAD',
        signal: AbortSignal.timeout(5000), // 5秒超时
      });
      const isAvailable = response.ok;
      console.log(isAvailable ? '✅ TTS 服务可用' : '❌ TTS 服务不可用');
      return isAvailable;
    } catch (error) {
      console.error('❌ TTS 服务检查失败:', error);
      return false;
    }
  }

  /**
   * 开始语音合成（优化版本）
   */
  async startSynthesis(text: string, callbacks: SpeechSynthesisCallbacks): Promise<void> {
    if (!text || !text.trim()) {
      callbacks.onError?.('文本不能为空');
      return;
    }

    // 停止当前正在播放的音频
    this.stopPlayback();

    this.callbacks = callbacks;
    this.isPlaying = true;

    try {
      const trimmedText = text.trim();

      // 创建 AbortController 用于取消请求
      this.abortController = new AbortController();

      // 第一步：提交生成请求
      console.log('📤 提交生成请求...');
      const startTime = Date.now();
      
      const response = await fetch(`${TTS_BASE_URL}/gradio_api/call/generate_audio`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          data: [
            trimmedText,             // tts_text
            '预训练音色',             // mode_checkbox_group
            this.currentVoiceType,   // sft_dropdown (音色选择)
            '',                      // prompt_text
            null,                    // prompt_wav_upload
            null,                    // prompt_wav_record
            '',                      // instruct_text
            0,                       // seed
            true,                    // stream (流式推理)
            1.0,                     // speed (语速)
          ],
        }),
        signal: this.abortController.signal,
      });

      const requestTime = Date.now() - startTime;
      console.log(`✅ 请求响应时间: ${requestTime}ms`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      const eventId = result.event_id;

      console.log('✅ 获取到 event_id:', eventId);

      // 第二步：获取生成结果
      console.log('📥 开始获取生成结果...');
      await this.getAudioResult(eventId);

      const totalTime = Date.now() - startTime;
      console.log(`✅ 总耗时: ${totalTime}ms`);

    } catch (error: any) {
      if (error.name === 'AbortError') {
        // console.log('🛑 语音合成已取消');
      } else {
        // console.error('❌ 语音合成失败:', error);
        // console.error('错误详情:', {
        //   name: error.name,
        //   message: error.message,
        //   stack: error.stack,
        // });
        
        let errorMsg = '语音合成失败';
        if (error.message.includes('Failed to fetch')) {
          errorMsg = '网络连接失败，请检查 TTS 服务是否正常运行';
        } else if (error.message.includes('HTTP')) {
          errorMsg = `服务器错误: ${error.message}`;
        } else {
          errorMsg = error.message || '语音合成失败';
        }
        
        this.callbacks.onError?.(errorMsg);
      }
      this.isPlaying = false;
    }
  }

  /**
   * 获取音频结果（优化版本，支持重试和超时处理）
   */
  private async getAudioResult(eventId: string): Promise<void> {
    const maxAttempts = 60; // 最多尝试60次
    const retryDelay = 1000; // 每次重试间隔1秒
    let lastAudioUrl: string | null = null;
    let isStarted = false;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const response = await fetch(`${TTS_BASE_URL}/gradio_api/call/generate_audio/${eventId}`, {
          signal: this.abortController?.signal,
        });

        if (!response.ok) {
          console.warn(`尝试 ${attempt + 1}/${maxAttempts}: HTTP ${response.status}`);
          if (attempt < maxAttempts - 1) {
            await new Promise(resolve => setTimeout(resolve, retryDelay));
            continue;
          }
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('无法读取响应流');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let isCompleted = false;

        // 第一次成功连接时触发 onStart
        if (!isStarted) {
          this.callbacks.onStart?.();
          isStarted = true;
        }

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            // 检查事件类型
            if (line.startsWith('event: complete')) {
              isCompleted = true;
              console.log('✅ 检测到完成事件');
            }

            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.substring(6));

                // 处理数组格式的音频数据
                if (Array.isArray(data) && data.length > 0 && data[0]?.url) {
                  lastAudioUrl = data[0].url;
                  console.log('📦 收到音频 URL:', lastAudioUrl);
                }
                // 处理标准格式
                else if (data.msg === 'process_completed' && data.output?.data?.[0]?.url) {
                  lastAudioUrl = data.output.data[0].url;
                  isCompleted = true;
                  console.log('✅ 生成完成（标准格式）');
                }
                // 处理错误
                else if (data.msg === 'error') {
                  throw new Error(data.output || '生成失败');
                }
              } catch (e) {
                console.error('解析数据失败:', e);
              }
            }
          }
        }

        // 如果检测到完成且有音频 URL
        if (isCompleted && lastAudioUrl) {
          // 修复 URL 路径
          let audioUrl = lastAudioUrl;
          
          // 移除错误的 /gradio_a/ 前缀
          if (audioUrl.includes('/gradio_a/gradio_api/')) {
            audioUrl = audioUrl.replace('/gradio_a/gradio_api/', '/gradio_api/');
          }

          // 确保是完整 URL
          if (!audioUrl.startsWith('http')) {
            audioUrl = `${TTS_BASE_URL}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
          }

          console.log('🔊 最终音频 URL:', audioUrl);

          // 播放音频
          await this.playAudio(audioUrl);
          return;
        }

      } catch (error: any) {
        if (error.name === 'AbortError') {
          throw error;
        }
        console.error(`尝试 ${attempt + 1}/${maxAttempts} 失败:`, error);
        
        // 如果不是最后一次尝试，继续重试
        if (attempt < maxAttempts - 1) {
          await new Promise(resolve => setTimeout(resolve, retryDelay));
          continue;
        }
        throw error;
      }

      // 等待后重试
      await new Promise(resolve => setTimeout(resolve, retryDelay));
    }

    throw new Error('生成超时：超过最大重试次数');
  }

  /**
   * 播放音频（优化版本，添加更好的错误处理和状态管理）
   */
  private async playAudio(audioUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.audioElement = new Audio(audioUrl);

      // 设置预加载策略
      this.audioElement.preload = 'auto';

      // 音频加载成功
      this.audioElement.onloadeddata = () => {
        console.log('✅ 音频加载成功');
      };

      // 音频可以播放
      this.audioElement.oncanplay = () => {
        console.log('✅ 音频可以播放');
      };

      // 开始播放
      this.audioElement.onplay = () => {
        console.log('🔊 开始播放');
      };

      // 播放中
      this.audioElement.ontimeupdate = () => {
        // 可以在这里添加进度更新回调
        const progress = (this.audioElement!.currentTime / this.audioElement!.duration) * 100;
        if (progress > 0 && progress < 100) {
          // console.log(`播放进度: ${progress.toFixed(1)}%`);
        }
      };

      // 播放完成
      this.audioElement.onended = () => {
        console.log('✅ 播放完成');
        this.isPlaying = false;
        this.callbacks.onComplete?.();
        this.audioElement = null;
        resolve();
      };

      // 音频加载错误
      this.audioElement.onerror = (e) => {
        console.error('❌ 音频加载失败:', e);
        console.error('音频 URL:', audioUrl);
        
        const errorMsg = this.audioElement?.error 
          ? `音频加载失败: ${this.getMediaErrorMessage(this.audioElement.error.code)}`
          : '音频加载失败';
        
        this.isPlaying = false;
        this.callbacks.onError?.(errorMsg);
        this.audioElement = null;
        reject(new Error(errorMsg));
      };

      // 开始播放
      this.audioElement.play().catch((err) => {
        console.error('❌ 播放失败:', err);
        
        let errorMsg = '播放失败';
        if (err.name === 'NotAllowedError') {
          errorMsg = '播放失败: 浏览器阻止了自动播放，请手动点击播放';
        } else if (err.name === 'NotSupportedError') {
          errorMsg = '播放失败: 不支持的音频格式';
        }
        
        this.isPlaying = false;
        this.callbacks.onError?.(errorMsg);
        this.audioElement = null;
        reject(err);
      });
    });
  }

  /**
   * 获取媒体错误信息
   */
  private getMediaErrorMessage(code: number): string {
    switch (code) {
      case 1: // MEDIA_ERR_ABORTED
        return '音频加载被中止';
      case 2: // MEDIA_ERR_NETWORK
        return '网络错误';
      case 3: // MEDIA_ERR_DECODE
        return '音频解码失败';
      case 4: // MEDIA_ERR_SRC_NOT_SUPPORTED
        return '不支持的音频格式';
      default:
        return '未知错误';
    }
  }

  /**
   * 停止播放（优化版本，更完善的清理）
   */
  stopPlayback(): void {
    // 取消正在进行的请求
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }

    // 停止音频播放
    if (this.audioElement) {
      try {
        // 暂停播放
        this.audioElement.pause();
        
        // 重置播放位置
        this.audioElement.currentTime = 0;
        
        // 移除所有事件监听器
        this.audioElement.onloadeddata = null;
        this.audioElement.oncanplay = null;
        this.audioElement.onplay = null;
        this.audioElement.ontimeupdate = null;
        this.audioElement.onended = null;
        this.audioElement.onerror = null;
        
        // 清空音频源
        this.audioElement.src = '';
        this.audioElement.load();
        
        this.audioElement = null;
        console.log('✅ 已清理音频元素');
      } catch (error) {
        console.error('清理音频元素时出错:', error);
      }
    }

    this.isPlaying = false;
  }

  /**
   * 检查是否正在播放
   */
  isAudioPlaying(): boolean {
    return this.isPlaying;
  }

  /**
   * 获取当前播放进度（0-100）
   */
  getPlaybackProgress(): number {
    if (!this.audioElement || !this.audioElement.duration) {
      return 0;
    }
    return (this.audioElement.currentTime / this.audioElement.duration) * 100;
  }

  /**
   * 获取播放时间信息
   */
  getPlaybackTime(): { current: number; duration: number; remaining: number } {
    if (!this.audioElement) {
      return { current: 0, duration: 0, remaining: 0 };
    }
    const current = this.audioElement.currentTime || 0;
    const duration = this.audioElement.duration || 0;
    const remaining = duration - current;
    return { current, duration, remaining };
  }

  /**
   * 清理资源
   */
  dispose(): void {
    this.stopPlayback();
  }
}

// 导出单例
export const speechSynthesisService = new SpeechSynthesisService();
