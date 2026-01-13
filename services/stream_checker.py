import asyncio
import base64
import os
import subprocess
import shutil
import uuid
import tempfile
from static_ffmpeg import run

class StreamChecker:
    _ffmpeg_path = None

    @classmethod
    def get_ffmpeg_path(cls):
        """获取并验证 FFmpeg 路径"""
        if cls._ffmpeg_path:
            return cls._ffmpeg_path

        # 1. 优先尝试系统路径中的 ffmpeg
        sys_ffmpeg = shutil.which("ffmpeg")
        if sys_ffmpeg:
            try:
                # 简单验证是否能跑
                subprocess.run([sys_ffmpeg, "-version"], capture_output=True, timeout=2)
                cls._ffmpeg_path = sys_ffmpeg
                print(f"DEBUG: 使用系统 FFmpeg: {sys_ffmpeg}")
                return cls._ffmpeg_path
            except Exception as e:
                print(f"DEBUG: 系统 FFmpeg ({sys_ffmpeg}) 运行失败: {e}")

        # 2. 尝试 static-ffmpeg 下载的二进制
        try:
            static_ffmpeg = run.get_or_fetch_platform_executables_else_raise()[0]
            try:
                subprocess.run([static_ffmpeg, "-version"], capture_output=True, timeout=2)
                cls._ffmpeg_path = static_ffmpeg
                print(f"DEBUG: 使用 static-ffmpeg 二进制: {static_ffmpeg}")
                return cls._ffmpeg_path
            except Exception as e:
                print(f"DEBUG: static-ffmpeg 二进制 ({static_ffmpeg}) 运行失败: {e}")
        except Exception as e:
            print(f"DEBUG: 获取 static-ffmpeg 二进制失败: {e}")

        # 最后兜底
        cls._ffmpeg_path = "ffmpeg"
        print(f"DEBUG: 未找到有效 FFmpeg，兜底使用命令: {cls._ffmpeg_path}")
        return cls._ffmpeg_path

    @classmethod
    async def check_stream_visual(cls, url: str) -> dict:
        ffmpeg_exe = cls.get_ffmpeg_path()
        temp_filename = os.path.join(tempfile.gettempdir(), f"capture_{uuid.uuid4()}.jpg")
        
        # 核心参数：这些参数必须紧跟在 -i 之前以确保对输入流生效
        # 尤其是 -allowed_extensions ALL，在 Windows 下对于 .php 结尾的 HLS 流至关重要
        input_args = [
            "-protocol_whitelist", "file,http,https,tcp,tls,crypto,rtp,udp",
            "-allowed_extensions", "ALL",
            "-hls_flags", "noparse_hevc", # 某些流可能需要这个
            "-user_agent", "AptvPlayer/1.4.1",
            "-timeout", "5000000",       # 5秒超时 (单位微秒)
        ]
        
        # 输出参数
        output_args = [
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-an", "-sn",
            "-frames:v", "1",
            "-vf", "scale=320:-1",
            "-f", "image2",
            "-c:v", "mjpeg",
            temp_filename 
        ]

        # 策略 1: 强制 HLS。在 Windows FFmpeg 7.x 中，对于 .php 后缀的 HLS，必须显式 -f hls 且紧跟参数
        cmd_hls = [ffmpeg_exe] + input_args + ["-f", "hls", "-i", url] + output_args
        
        # 策略 2: 自动探测
        cmd_auto = [ffmpeg_exe] + input_args + ["-i", url] + output_args

        print(f"DEBUG: 尝试捕获截图: {url}")

        async def run_cmd(cmd):
            def run_ffmpeg():
                return subprocess.run(cmd, capture_output=True, timeout=20, env=os.environ.copy())
            return await asyncio.to_thread(run_ffmpeg)

        try:
            # 首先尝试强制 HLS 模式
            result = await run_cmd(cmd_hls)
            
            # 如果 HLS 模式失败，尝试普通模式
            if result.returncode != 0:
                print(f"DEBUG: HLS 模式捕获失败 (RC={result.returncode})，尝试自动探测模式...")
                result = await run_cmd(cmd_auto)

            if result.returncode == 0 and os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                with open(temp_filename, "rb") as f:
                    img_data = f.read()
                
                b64 = base64.b64encode(img_data).decode('utf-8')
                return {"url": url, "status": True, "image": f"data:image/jpeg;base64,{b64}"}
            else:
                err_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else "FFmpeg produced no image."
                # 针对 Windows 的特殊错误记录
                print(f"DEBUG: [{url}] 检测失败 (RC={result.returncode}): {err_msg[:300]}")
                return {"url": url, "status": False, "error": "FFmpeg detection failed"}

        except subprocess.TimeoutExpired:
            print(f"DEBUG: [{url}] 检测超时")
            return {"url": url, "status": False, "error": "Detection Timeout"}
        except Exception as e:
            print(f"DEBUG: 运行异常: {e}")
            return {"url": url, "status": False, "error": str(e)}
        finally:
            if os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except:
                    pass
