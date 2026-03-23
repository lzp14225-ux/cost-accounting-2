"""
转录引擎 - 基于 OpenAI Whisper 的转录核心
"""

import whisper
import torch
import re
import os
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import numpy as np
from .dict_manager import DictionaryManager
from .prompt_engine import PromptEngine
from .utils import convert_to_simplified_chinese, normalize_zh_punctuation
from .console import info, debug
from shared.config import settings


class CodeWhisper:
    """主转录引擎"""

    def __init__(self, model_name: str = "medium", dict_path: Optional[str] = None, download_root: Optional[str] = None):
        """
         CodeWhisper 初始化，同时预加载字典的特定术语并将其构建为提示词喂给Whisper进行预热；模型默认medium
        Args:
            model_name: Whisper 模型 (tiny, base, small, medium, large)
            dict_path: 自定义字典路径，支持后续拓展todo
            download_root: 模型下载/缓存目录，默认使用项目目录下的 models 文件夹
        """
        info(f"📦 Whisper 模型: {model_name}")
        self._configure_ffmpeg_path()

        # 设置模型下载目录
        if download_root is None:
            # 默认使用项目目录下的 models 文件夹
            project_root = Path(__file__).parent.parent
            download_root = str(project_root / "models")
            os.makedirs(download_root, exist_ok=True)
            info(f"📁 模型缓存目录: {download_root}")
        
        # 显式设定设备与精度：优先使用 NVIDIA CUDA，其次回退 CPU
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        if self.device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            info(f"🚀 使用 GPU 加速: {gpu_name}")
            info(f"   CUDA 版本: {torch.version.cuda}")
            info(f"   显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        else:
            info(f"⚠️  使用 CPU 模式 (FP32)")
            info(f"   提示：安装 CUDA 版本的 PyTorch 可启用 GPU 加速")

        # openai-whisper 会在 CUDA 上自动使用 fp16，在 CPU 上用 fp32
        # 使用自定义的 download_root
        self.model = whisper.load_model(model_name, device=self.device, download_root=download_root)
        self.model_name = model_name
        self.download_root = download_root

        debug("📚 加载字典管理器")
        self.dict_manager = DictionaryManager(dict_path)

        debug("🚀 加载智能提示词引擎")
        self.prompt_engine = PromptEngine()

        # 使用新的 PromptEngine 构建提示词
        # 构建初始提示词喂给 Whisper，减少识别错误
        self.programmer_prompt = self.prompt_engine.build_prompt()
        # 例如: "计算机行业从业者：提测、联调、排期、Vue、React、数据库..."

        info(f"💡 当前提示词: {self.programmer_prompt}")

        info("✅ CodeWhisper 初始化完成")

    def _configure_ffmpeg_path(self) -> None:
        ffmpeg_path = (settings.FFMPEG_PATH or "").strip()
        if ffmpeg_path:
            ffmpeg_target = Path(ffmpeg_path)
            ffmpeg_dir = ffmpeg_target.parent if ffmpeg_target.is_file() else ffmpeg_target
            if ffmpeg_dir.exists():
                os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
                info(f"🎬 FFmpeg 路径已注入: {ffmpeg_dir}")
            else:
                info(f"⚠️ FFmpeg 路径不存在: {ffmpeg_path}")

        resolved = shutil.which("ffmpeg")
        if resolved:
            info(f"✅ FFmpeg 可用: {resolved}")
        else:
            info("⚠️ 未找到 ffmpeg，可在 .env 中设置 FFMPEG_PATH")

    def _audio_level_stats(self, audio_file: str) -> Tuple[float, float, float]:
        """
        读取音频并计算强度统计信息，用于快速判断“几乎静音”的输入。

        Returns:
            (duration_seconds, rms, peak)
        """
        try:
            audio = whisper.load_audio(audio_file)
        except Exception:
            # 读取失败时不做静音判定（避免误判直接跳过转录）
            return -1.0, 0.0, 0.0

        if audio is None or len(audio) == 0:
            return 0.0, 0.0, 0.0

        duration_seconds = float(len(audio) / whisper.audio.SAMPLE_RATE)
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
        peak = float(np.max(np.abs(audio)))
        return duration_seconds, rms, peak

    def _looks_like_repetition_loop(self, text: str, max_repeat: int = 10) -> bool:
        """
        检测明显的“循环重复”幻觉（常见于静音/低质量音频）。

        目标是过滤掉极端情况：某个词/字符/短语连续重复很多次。
        """
        if not text:
            return False

        normalized = re.sub(r"\s+", " ", text.strip())
        if not normalized:
            return False

        # 1) 按空格分词：检测连续相同词的超长 run（更适用于英文/夹杂英文）
        words = [w for w in normalized.split(" ") if w]
        if len(words) >= max_repeat:
            run = 1
            for idx in range(1, len(words)):
                if words[idx] == words[idx - 1]:
                    run += 1
                    if run >= max_repeat:
                        return True
                else:
                    run = 1

        # 2) 中文常见是无空格输出：去除标点/空白后做字符与短语重复检测
        compact = re.sub(r"[\\s，。！？,.!?:;；、】【\\[\\]()（）\"'“”‘’—…·]+", "", normalized)
        if len(compact) < max_repeat:
            return False

        # 2.1) 单字符重复（如 “啊啊啊啊...”）
        if re.search(rf"(.)\\1{{{max_repeat - 1},}}", compact):
            return True

        # 2.2) 短语重复（如 “谢谢观看谢谢观看...”）
        # 尝试 2~10 字符的短片段，避免过于昂贵
        for unit_len in range(2, 11):
            if len(compact) < unit_len * max_repeat:
                continue
            if re.search(rf"(.{{{unit_len}}})\\1{{{max_repeat - 1},}}", compact):
                return True

        return False

    def _filter_hallucinated_segments(
        self,
        segments: List[dict],
        *,
        max_repeat: int = 10,
        no_speech_prob_threshold: float = 0.8,
        avg_logprob_threshold: float = -0.8,
        compression_ratio_threshold: float = 2.4,
    ) -> List[dict]:
        """
        在 Whisper 输出后做一次轻量过滤，剔除明显静音/乱码/重复循环段。

        - no_speech_prob 高且 avg_logprob 低：常见静音幻觉
        - compression_ratio 过高：常见重复/乱码
        - 文本出现明显循环重复：常见“卡住式”幻觉
        """
        kept: List[dict] = []
        for seg in segments or []:
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            no_speech_prob = float(seg.get("no_speech_prob", 0.0) or 0.0)
            avg_logprob = float(seg.get("avg_logprob", 0.0) or 0.0)
            compression_ratio = float(seg.get("compression_ratio", 0.0) or 0.0)

            # 参考 whisper 的静音跳过逻辑：no_speech_prob 高且 logprob 低时判为静音
            if no_speech_prob >= no_speech_prob_threshold and avg_logprob <= avg_logprob_threshold:
                continue

            # 重复/乱码过滤
            if compression_ratio_threshold is not None and compression_ratio > compression_ratio_threshold:
                continue

            # 循环重复过滤
            if self._looks_like_repetition_loop(text, max_repeat=max_repeat):
                continue

            kept.append(seg)

        return kept

    def _remove_prompt_prefix(self, text: str) -> str:
        """
        过滤掉转录结果中的提示词前缀

        Whisper 在静音或音质差时，可能把 initial_prompt 当成转录结果输出
        """
        if not text:
            return text

        # 获取提示词前缀
        prompt_prefix = self.prompt_engine.config.get("prompt_prefix", "计算机行业从业者：")

        # 如果转录结果以提示词前缀开头，移除它
        if text.startswith(prompt_prefix):
            text = text[len(prompt_prefix):].strip()
            # 如果剩余内容也是提示词的一部分（术语列表），可能整个都是幻觉
            # 检查是否只剩下术语和标点
            if self._is_only_prompt_content(text):
                return ""

        return text

    def _is_only_prompt_content(self, text: str) -> bool:
        """检查文本是否只包含提示词内容（术语列表）"""
        if not text:
            return True

        # 移除常见分隔符和标点
        cleaned = text.replace("、", "").replace("，", "").replace("。", "").replace(" ", "")

        # 获取所有术语
        all_terms = set(self.prompt_engine.base_dict)
        for term_info in self.prompt_engine.user_dict:
            all_terms.add(term_info.get("term", ""))

        # 检查清理后的文本是否全部由术语组成
        remaining = cleaned
        for term in sorted(all_terms, key=len, reverse=True):
            remaining = remaining.replace(term, "")

        # 如果剩余内容为空或很短，说明全是术语
        return len(remaining) <= 2

    def transcribe(
        self,
        audio_file: str,
        language: Optional[str] = "zh",
        fix_programmer_terms: bool = True,
        verbose: bool = True,
        temperature: float = 0.0,
        hallucination_filter: bool = True,
        silence_rms_threshold: float = 0.002,
        silence_peak_threshold: float = 0.02,
        *,
        use_initial_prompt: bool = True,
        learn_user_terms: bool = True,
    ) -> Dict:
        """
        转录音频文件

        Args:
            audio_file: 音频文件路径
            language: 语言代码 (默认zh中文模型)
            fix_programmer_terms: 是否修正程序员术语默认为True
            verbose: 是否打印详细信息 默认为True (打印输出状态、提示词加载、繁简转换、术语修正等步骤)
            temperature: 控制模型的“随机性”，范围通常在0—1。默认为0，数值越高，输出越有随机性（不推荐用于语音转录）
            hallucination_filter: 是否启用幻觉/重复过滤（默认启用）
            silence_rms_threshold: 静音 RMS 阈值（越大越激进）
            silence_peak_threshold: 静音 Peak 阈值（越大越激进）
            use_initial_prompt: 是否把提示词喂给 Whisper（默认启用）。分块/低质量音频建议关闭以减少“提示词幻觉”。
            learn_user_terms: 是否根据本次转录结果更新用户术语库（默认启用）。分块转录建议关闭以避免频繁写盘。


        Returns:
            包含转录结果的字典
        """
        if verbose:
            debug(f"🎙️ 转录中 {audio_file} (语言: {language})")

        # 快速静音判断：避免静音输入触发 Whisper 产生“重复幻觉”
        if hallucination_filter:
            duration_seconds, rms, peak = self._audio_level_stats(audio_file)
            if verbose:
                debug(f"🔇 音频强度: 时长={duration_seconds:.2f}s, rms={rms:.5f}, peak={peak:.5f}")

            # duration_seconds < 0 表示无法读取音频，跳过静音判断
            if duration_seconds == 0.0:
                if verbose:
                    debug("⏭️ 音频为空，跳过转录")
                return {
                    "text": "",
                    "segments": [],
                    "language": language,
                    "_skipped_reason": "empty_audio",
                }

            if duration_seconds > 0.0 and (rms < silence_rms_threshold and peak < silence_peak_threshold):
                if verbose:
                    debug("⏭️ 检测到几乎静音，跳过转录")
                return {
                    "text": "",
                    "segments": [],
                    "language": language,
                    "_skipped_reason": "silence",
                }

        # 调用 Whisper 进行转录（使用初始化时缓存的提示词）
        # 注意：这里verbose=False 是指 OpenAI 的Whisper 自身的调试日志（解码进度等）
        # 而用户的 verbose 参数控制的是 CodeWhisper 的进度日志（上面的if verbose）
        result = self.model.transcribe(
            audio_file,
            language=language,
            initial_prompt=(self.programmer_prompt if use_initial_prompt else None),
            # openai-whisper 新版本：verbose=False 会显示 tqdm 进度条；verbose=None 才会安静
            verbose=None,
            temperature=temperature,
            # 防止 Whisper 幻觉重复 bug
            condition_on_previous_text=False,  # 禁用前文依赖，减少重复循环
            compression_ratio_threshold=2.4,   # 压缩比阈值，超过则认为是重复/乱码
            no_speech_threshold=0.6,           # 静音检测阈值，减少静音段幻觉
            # 避免 CPU 上 fp16 警告噪音
            fp16=(self.device == "cuda"),
        )

        if verbose:
            debug("✅ 转录完成")

        # 过滤掉提示词前缀（Whisper 幻觉问题：静音时可能把 initial_prompt 当成转录结果）
        result["text"] = self._remove_prompt_prefix(result["text"])
        for segment in result.get("segments", []):
            segment["text"] = self._remove_prompt_prefix(segment.get("text", ""))

        # 将繁体转换为简体
        if verbose:
            debug("🧹 转换繁体为简体")

        result["text"] = convert_to_simplified_chinese(result["text"])
        for segment in result["segments"]:
            segment["text"] = convert_to_simplified_chinese(segment["text"])

        # 规范化中文标点（如英文逗号 -> 中文逗号）
        if language and language.lower().startswith("zh"):
            result["text"] = normalize_zh_punctuation(result["text"])
            for segment in result["segments"]:
                segment["text"] = normalize_zh_punctuation(segment["text"])

        # 过滤静音/乱码/循环重复分段，减少“幻觉重复”
        if hallucination_filter:
            filtered_segments = self._filter_hallucinated_segments(result.get("segments", []))
            if len(filtered_segments) != len(result.get("segments", [])) and verbose:
                debug(f"🧽 幻觉过滤: {len(result.get('segments', []))} -> {len(filtered_segments)} 段")
            result["segments"] = filtered_segments
            result["text"] = "".join([seg.get("text", "") for seg in filtered_segments]).strip()

            if language and language.lower().startswith("zh"):
                result["text"] = normalize_zh_punctuation(result["text"])

        # 替换术语
        if fix_programmer_terms:
            if verbose:
                debug("🛠 修正为工业模具领域术语")

            # 只修正正文文本一次，避免重复修正
            result["text"] = self.dict_manager.fix_text(result["text"], accumulate=False)

            if language and language.lower().startswith("zh"):
                result["text"] = normalize_zh_punctuation(result["text"])

        # 学习用户习惯：检测文本中出现的术语并更新用户术语库
        if learn_user_terms:
            if verbose:
                debug("🧠 学习用户习惯")

            # 方法1：从修正记录中获取术语（优先，更精准）
            detected_terms = self.dict_manager.get_detected_terms_from_corrections()

            # 方法2：从最终文本中检测术语（补充）
            detected_terms_from_text = self.dict_manager.detect_terms_in_text(result["text"])
            detected_terms.update(detected_terms_from_text)

            if detected_terms:
                if verbose:
                    debug(f"  检测到术语: {', '.join(list(detected_terms)[:5])}{'...' if len(detected_terms) > 5 else ''}")
                # 更新用户术语库
                self.prompt_engine.update_user_terms(detected_terms)

                # 重新构建提示词（下次转录使用）
                self.programmer_prompt = self.prompt_engine.build_prompt()

        return result

    def get_supported_models(self) -> list:
        """获取支持的模型列表"""
        return ["tiny", "base", "small", "medium", "large"]

    def get_dict_stats(self) -> Dict:
        """获取字典统计信息"""
        return self.dict_manager.get_stats()

    def get_dict_categories(self) -> Dict:
        """获取字典分类统计"""
        return self.dict_manager.list_categories()

    def get_prompt_stats(self) -> Dict:
        """获取提示词引擎统计信息"""
        return self.prompt_engine.get_stats()
