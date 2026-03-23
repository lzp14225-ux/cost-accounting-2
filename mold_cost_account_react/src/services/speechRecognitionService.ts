// 语音识别配置 - 使用环境变量
import config from '../config/env'

const SPEECH_CONFIG = {
  apiUrl: `${config.SPEECH_RECOGNITION_BASE_URL}/api/transcribe/stream`,
  model: 'small',
  language: 'zh',
  fixTerms: true,
  format: 'wav',
};

interface SpeechRecognitionCallbacks {
  onStart?: () => void;
  onResult?: (text: string, isFinal: boolean) => void;
  onEnd?: () => void;
  onError?: (error: string) => void;
}

export class SpeechRecognitionService {
  private audioContext: AudioContext | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private audioChunks: Blob[] = [];
  private isRecording = false;
  private callbacks: SpeechRecognitionCallbacks = {};

  /**
   * 将 Blob 转换为 Base64
   */
  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64String = reader.result as string;
        // 移除 data:audio/wav;base64, 前缀
        const base64Data = base64String.split(',')[1];
        resolve(base64Data);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  /**
   * 开始录音和识别
   */
  async startRecognition(callbacks: SpeechRecognitionCallbacks): Promise<void> {
    if (this.isRecording) {
      console.warn('已经在录音中');
      return;
    }

    this.callbacks = callbacks;
    this.audioChunks = [];

    try {
      // 1. 获取麦克风权限
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
        } 
      });
      console.log('🎤 麦克风权限获取成功');

      // 2. 创建 MediaRecorder
      const options = { mimeType: 'audio/webm' };
      this.mediaRecorder = new MediaRecorder(this.mediaStream, options);

      // 3. 收集音频数据
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      // 4. 录音停止时发送数据
      this.mediaRecorder.onstop = async () => {
        
        try {
          // 合并音频数据
          const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });

          // 转换为 Base64
          const base64Audio = await this.blobToBase64(audioBlob);

          // 发送到语音识别接口
          await this.sendToRecognitionAPI(base64Audio);

        } catch (error: any) {
          this.callbacks.onError?.(error.message || '处理音频数据失败');
        }
      };

      // 5. 开始录音
      this.mediaRecorder.start();
      this.isRecording = true;
      console.log('🎙️ 开始录音');
      this.callbacks.onStart?.();

    } catch (error: any) {
      console.error('❌ 启动录音失败:', error);
      this.callbacks.onError?.(error.message || '启动录音失败');
      throw error;
    }
  }

  /**
   * 发送音频数据到识别接口
   */
  private async sendToRecognitionAPI(base64Audio: string): Promise<void> {
    try {
      console.log('📤 发送识别请求到:', SPEECH_CONFIG.apiUrl);

      // 构建 FormData
      const formData = new FormData();
      formData.append('audio_data', base64Audio);
      formData.append('model', SPEECH_CONFIG.model);
      formData.append('language', SPEECH_CONFIG.language);
      formData.append('fix_terms', SPEECH_CONFIG.fixTerms.toString());
      formData.append('format', SPEECH_CONFIG.format);

      // 发送请求
      const response = await fetch(SPEECH_CONFIG.apiUrl, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`识别请求失败: ${response.status} ${response.statusText}`);
      }

      const result = await response.json();
      console.log('📥 识别结果:', result);

      if (result.success && result.text) {
        // 返回最终识别结果
        this.callbacks.onResult?.(result.text, true);
        this.callbacks.onEnd?.();
      } else {
        throw new Error(result.message || '识别失败');
      }

    } catch (error: any) {
      console.error('❌ 识别请求失败:', error);
      this.callbacks.onError?.(error.message || '识别请求失败');
    }
  }

  /**
   * 停止录音和识别
   */
  stopRecognition(): void {
    if (!this.isRecording) {
      return;
    }

    this.isRecording = false;

    // 停止 MediaRecorder
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }

    // 停止媒体流
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
  }

  /**
   * 检查是否正在录音
   */
  isActive(): boolean {
    return this.isRecording;
  }

  /**
   * 清理资源
   */
  dispose(): void {
    this.stopRecognition();
    
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    
    this.mediaRecorder = null;
    this.audioChunks = [];
  }
}

// 导出单例
export const speechRecognitionService = new SpeechRecognitionService();
