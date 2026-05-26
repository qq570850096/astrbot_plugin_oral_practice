"""
Audio utility module — 音频工具模块

Provides async-safe audio format conversion, base64 decoding,
duration detection, and temp directory management.
Uses pydub (with ffmpeg backend) for audio processing,
wrapped in asyncio.to_thread to keep the event loop responsive.
"""

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from typing import Optional

from astrbot.api import logger

# Supported input formats and their pydub codec hints
# 支持的输入格式及其 pydub 编解码器提示
_FORMAT_HINTS: dict[str, str] = {
    ".mp3": "mp3",
    ".silk": "silk",
    ".slk": "silk",
    ".amr": "amr",
    ".ogg": "ogg",
    ".wav": "wav",
    ".flac": "flac",
    ".m4a": "m4a",
    ".wma": "wma",
    ".aac": "aac",
    ".webm": "webm",
}

# Module-level temp directory path (lazily initialized)
# 模块级临时目录路径（延迟初始化）
_temp_dir: Optional[str] = None


def ensure_temp_dir() -> str:
    """Ensure the temp directory exists and return its path.

    Creates a persistent temp directory under the system temp folder
    for storing intermediate audio files during processing.
    确保临时目录存在并返回其路径。

    Returns:
        str: Absolute path to the temp directory.
    """
    global _temp_dir
    if _temp_dir is not None and os.path.isdir(_temp_dir):
        return _temp_dir

    base = os.path.join(tempfile.gettempdir(), "astrbot_oral_practice")
    os.makedirs(base, exist_ok=True)
    _temp_dir = base
    logger.info(f"[audio_utils] Temp directory ready: {_temp_dir}")
    return _temp_dir


def _sync_convert_to_wav_pcm(
    input_path: str, output_path: str, sample_rate: int = 16000
) -> str:
    """Synchronous audio conversion — runs in a thread via asyncio.to_thread.

    Converts any supported audio format to WAV PCM 16-bit mono.
    同步音频转换，将通过 asyncio.to_thread 在线程中运行。

    Args:
        input_path: Path to the source audio file.
        output_path: Desired output WAV file path.
        sample_rate: Target sample rate in Hz (default: 16000 for speech).

    Returns:
        str: The output file path on success.

    Raises:
        FileNotFoundError: If the input file does not exist.
        ValueError: If the audio format is unsupported or conversion fails.
    """
    from pydub import AudioSegment

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input audio file not found: {input_path}")

    ext = Path(input_path).suffix.lower()
    fmt = _FORMAT_HINTS.get(ext)

    if fmt is None:
        logger.warning(
            f"[audio_utils] Unsupported audio extension '{ext}', "
            f"attempting raw decode for: {input_path}"
        )
        # Try letting ffmpeg auto-detect the format
        # 尝试让 ffmpeg 自动检测格式
        fmt = None

    try:
        if fmt:
            audio = AudioSegment.from_file(input_path, format=fmt)
        else:
            audio = AudioSegment.from_file(input_path)
    except Exception as e:
        raise ValueError(
            f"Failed to decode audio file '{input_path}' "
            f"(detected format: {fmt or 'auto'}): {e}"
        ) from e

    # Convert to mono, 16-bit PCM, target sample rate
    # 转换为单声道、16 位 PCM、目标采样率
    audio = audio.set_channels(1).set_frame_rate(sample_rate).set_sample_width(2)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    audio.export(output_path, format="wav")
    logger.info(
        f"[audio_utils] Converted '{input_path}' -> '{output_path}' "
        f"(mono, {sample_rate}Hz, 16-bit PCM)"
    )
    return output_path


async def convert_to_wav_pcm(
    input_path: str, output_path: str, sample_rate: int = 16000
) -> str:
    """Convert any audio format (MP3, SILK, AMR, OGG, etc.) to WAV PCM 16-bit mono.

    Runs the blocking pydub/ffmpeg conversion in a background thread
    to avoid blocking the async event loop.
    将任意音频格式转换为 WAV PCM 16 位单声道。

    Args:
        input_path: Path to the source audio file.
        output_path: Desired output WAV file path.
        sample_rate: Target sample rate in Hz (default: 16000 for speech).

    Returns:
        str: The output file path on success.

    Raises:
        FileNotFoundError: If the input file does not exist.
        ValueError: If conversion fails.
    """
    return await asyncio.to_thread(
        _sync_convert_to_wav_pcm, input_path, output_path, sample_rate
    )


async def decode_base64_audio(b64_data: str, output_path: str) -> str:
    """Decode base64-encoded audio data and write to a file.

    解码 base64 编码的音频数据并写入文件。

    Args:
        b64_data: Base64-encoded audio string. May include a
                  data URI prefix (e.g., 'data:audio/wav;base64,...').
        output_path: Path to write the decoded audio bytes.

    Returns:
        str: The output file path.

    Raises:
        ValueError: If the base64 data is invalid or empty.
    """
    if not b64_data:
        raise ValueError("Empty base64 audio data provided")

    # Strip optional data URI prefix / 去除可选的 data URI 前缀
    if "," in b64_data and b64_data.startswith("data:"):
        b64_data = b64_data.split(",", 1)[1]

    try:
        audio_bytes = base64.b64decode(b64_data)
    except Exception as e:
        raise ValueError(f"Failed to decode base64 audio data: {e}") from e

    if len(audio_bytes) == 0:
        raise ValueError("Decoded audio data is empty (0 bytes)")

    # Write asynchronously via thread / 通过线程异步写入
    def _write() -> str:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    result = await asyncio.to_thread(_write)
    logger.info(
        f"[audio_utils] Decoded base64 audio -> '{result}' "
        f"({len(audio_bytes)} bytes)"
    )
    return result


async def get_audio_duration(audio_path: str) -> float:
    """Get the duration of an audio file in seconds.

    获取音频文件的时长（秒）。

    Args:
        audio_path: Path to the audio file.

    Returns:
        float: Duration in seconds.

    Raises:
        FileNotFoundError: If the audio file does not exist.
        ValueError: If the file cannot be read as audio.
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    def _get_duration() -> float:
        from pydub import AudioSegment

        ext = Path(audio_path).suffix.lower()
        fmt = _FORMAT_HINTS.get(ext)

        try:
            if fmt:
                audio = AudioSegment.from_file(audio_path, format=fmt)
            else:
                audio = AudioSegment.from_file(audio_path)
        except Exception as e:
            raise ValueError(
                f"Cannot read audio file '{audio_path}' for duration: {e}"
            ) from e

        return len(audio) / 1000.0  # pydub returns milliseconds / pydub 返回毫秒

    duration = await asyncio.to_thread(_get_duration)
    logger.debug(f"[audio_utils] Audio duration for '{audio_path}': {duration:.2f}s")
    return duration
