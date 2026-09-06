"""
FFmpeg Processing Service Module
Handles aspect-ratio and orientation probing, smart conditional normalization,
uploaded file direct merge, and sequential multi-track concatenation (Video + Video, Video + Audio, Audio + Audio).
"""

import os
import time
import uuid
import json
import logging
import tempfile
import subprocess
import asyncio
from typing import List, Tuple, Callable, Any, Generator, Optional, Dict
from concurrent.futures import ThreadPoolExecutor

from config import (
    FFMPEG_PATH,
    FFPROBE_PATH,
    MAX_CONCURRENT_FFMPEG,
    FFMPEG_TIMEOUT_SECONDS,
    MAX_THREAD_WORKERS,
)
from services.downloader_service import download_media_async

logger = logging.getLogger("FFmpegService")

ffmpeg_thread_pool = ThreadPoolExecutor(max_workers=MAX_THREAD_WORKERS)
_ffmpeg_semaphore = asyncio.Semaphore(MAX_CONCURRENT_FFMPEG)


def make_temp_filepath(suffix: str) -> str:
    """Safely creates a temporary file and closes its handle immediately to prevent Windows file-lock errors."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        return tf.name


def get_ffmpeg_semaphore() -> asyncio.Semaphore:
    """Returns global concurrency semaphore for FFmpeg encoding jobs."""
    return _ffmpeg_semaphore


def has_video_stream(file_path: str) -> bool:
    """Checks if media file contains at least one active video stream."""
    try:
        cmd = [
            FFPROBE_PATH, "-v", "quiet", "-select_streams", "v",
            "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return bool(res.stdout and res.stdout.strip())
    except Exception:
        return False


def probe_media_stream_details(file_path: str) -> Dict[str, Any]:
    """
    Probes complete stream details for smart conditional normalization:
    - width, height (accounting for rotation)
    - vcodec, acodec
    - fps / r_frame_rate
    - pix_fmt
    - sample_rate, channels
    - has_video, has_audio, duration
    """
    details: Dict[str, Any] = {
        "has_video": False,
        "has_audio": False,
        "width": 0,
        "height": 0,
        "vcodec": "",
        "acodec": "",
        "fps": 30.0,
        "pix_fmt": "",
        "sample_rate": 44100,
        "channels": 2,
        "duration": 0.0,
    }
    try:
        cmd = [
            FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.stdout:
            data = json.loads(res.stdout)
            format_info = data.get("format", {})
            details["duration"] = float(format_info.get("duration", 0.0) or 0.0)

            for s in data.get("streams", []):
                ctype = s.get("codec_type")
                if ctype == "video" and not details["has_video"]:
                    details["has_video"] = True
                    details["vcodec"] = s.get("codec_name", "")
                    details["pix_fmt"] = s.get("pix_fmt", "")
                    w = int(s.get("width", 0))
                    h = int(s.get("height", 0))
                    tags = s.get("tags", {})
                    side_data = s.get("side_data_list", [])
                    rot = 0
                    if "rotate" in tags:
                        try:
                            rot = int(float(tags["rotate"]))
                        except Exception:
                            pass
                    for sd in side_data:
                        if "rotation" in sd:
                            try:
                                rot = int(float(sd["rotation"]))
                            except Exception:
                                pass
                    if rot in [90, 270, -90, -270]:
                        w, h = h, w
                    if w > 0 and h > 0:
                        w = w if w % 2 == 0 else w + 1
                        h = h if h % 2 == 0 else h + 1
                        details["width"] = w
                        details["height"] = h

                    # Frame rate parsing
                    r_fps = s.get("r_frame_rate", "30/1")
                    if "/" in r_fps:
                        parts = r_fps.split("/")
                        if len(parts) == 2 and float(parts[1]) > 0:
                            details["fps"] = round(float(parts[0]) / float(parts[1]), 2)
                    elif r_fps:
                        details["fps"] = float(r_fps)

                elif ctype == "audio" and not details["has_audio"]:
                    details["has_audio"] = True
                    details["acodec"] = s.get("codec_name", "")
                    details["sample_rate"] = int(s.get("sample_rate", 44100) or 44100)
                    details["channels"] = int(s.get("channels", 2) or 2)
    except Exception as e:
        logger.debug(f"ffprobe stream details probe notice for {file_path}: {e}")

    return details


def probe_video_dimensions(file_path: str) -> Optional[Tuple[int, int]]:
    """Legacy helper for probing video dimensions."""
    d = probe_media_stream_details(file_path)
    if d["width"] > 0 and d["height"] > 0:
        return d["width"], d["height"]
    return None


async def process_audio_merge(
    target_urls: Optional[List[str]] = None,
    client_ip: str = "127.0.0.1",
    extract_fn: Optional[Callable] = None,
    local_file_paths: Optional[List[str]] = None,
    force_audio_only: bool = False,
) -> Tuple[Generator[bytes, None, None], str, str]:
    """
    High-Performance Sequential Multi-Track Merger Engine:
    - If local_file_paths provided (Uploaded files from user device): ZERO second re-download, directly merges files.
    - If target_urls provided: Downloads media tracks in parallel.
    - If force_audio_only is True: Always extracts/uses audio only and outputs a pure 320kbps MP3.
    - Determines native orientation (16:9 Landscape or 9:16 Portrait) from the first video track when merging videos.
    - Smart normalization: Only re-encodes when codecs/resolutions/audio mismatch; copies stream when compatible.
    - Sequentially concatenates all segments in selection order (Track 1 -> Track 2 -> Track 3...).
    - Returns (stream_generator, output_filename, media_type).
    """
    loop = asyncio.get_running_loop()
    temp_files: List[str] = []

    downloaded_tracks: List[Dict[str, Any]] = []

    # ── PATH A: Direct Local Files (From Client-side Upload / Cache - ZERO Re-download) ──
    if local_file_paths and len(local_file_paths) > 0:
        for idx, fpath in enumerate(local_file_paths):
            if not os.path.exists(fpath) or os.path.getsize(fpath) < 100:
                raise Exception(f"Uploaded track {idx+1} is missing or empty.")
            temp_files.append(fpath)
            details = probe_media_stream_details(fpath)
            downloaded_tracks.append({
                "idx": idx,
                "target_url": f"local_file_{idx+1}",
                "downloaded_path": fpath,
                "has_video": False if force_audio_only else details["has_video"],
                "title": f"Track {idx+1}",
                "details": details
            })

    # ── PATH B: URL-based Fallback (Resolves and downloads tracks) ──────────────
    elif target_urls and extract_fn:
        # Step 1: Resolve all track streams in parallel
        async def _resolve_track(idx: int, t_url: str):
            if force_audio_only:
                res = await extract_fn(t_url, format_type="mp3", client_ip=client_ip)
                data = res.get("data", {})
                return {
                    "idx": idx,
                    "target_url": t_url,
                    "raw_stream_url": data.get("raw_stream_url") or data.get("download_url") or "",
                    "is_video": False,
                    "title": data.get("title", f"Track {idx+1}")
                }
            else:
                try:
                    res = await extract_fn(t_url, format_type="mp4", client_ip=client_ip)
                    data = res.get("data", {})
                    return {
                        "idx": idx,
                        "target_url": t_url,
                        "raw_stream_url": data.get("raw_stream_url") or data.get("download_url") or "",
                        "is_video": data.get("format_type") == "mp4",
                        "title": data.get("title", f"Track {idx+1}")
                    }
                except Exception:
                    # Fallback to audio extraction
                    try:
                        res = await extract_fn(t_url, format_type="mp3", client_ip=client_ip)
                        data = res.get("data", {})
                        return {
                            "idx": idx,
                            "target_url": t_url,
                            "raw_stream_url": data.get("raw_stream_url") or data.get("download_url") or "",
                            "is_video": False,
                            "title": data.get("title", f"Track {idx+1}")
                        }
                    except Exception as err:
                        raise Exception(f"Track {idx+1} ({t_url}) stream resolution failed: {str(err)}")

        track_infos = await asyncio.gather(*[_resolve_track(i, u) for i, u in enumerate(target_urls)])

        # Step 2: Download each media track in parallel
        async def _download_track(item: dict):
            idx = item["idx"]
            tmp_base = make_temp_filepath(f"_raw_{idx}")
            temp_files.append(tmp_base)

            dl_path = await download_media_async(
                target_url=item["target_url"],
                raw_stream_url=item["raw_stream_url"],
                is_video=item["is_video"],
                base_path=tmp_base,
                client_ip=client_ip
            )

            if not dl_path or not os.path.exists(dl_path) or os.path.getsize(dl_path) < 1000:
                raise Exception(f"Track {idx+1} ({item['title']}) download failed.")

            temp_files.append(dl_path)
            details = probe_media_stream_details(dl_path)
            return {
                **item,
                "downloaded_path": dl_path,
                "has_video": False if force_audio_only else details["has_video"],
                "details": details
            }

        downloaded_tracks = await asyncio.gather(*[_download_track(t) for t in track_infos])
    else:
        raise Exception("No media tracks or files provided for merge.")

    downloaded_tracks.sort(key=lambda x: x["idx"])
    has_any_video = False if force_audio_only else any(t["has_video"] for t in downloaded_tracks)

    # Determine native orientation / aspect ratio from the primary video track
    target_w, target_h = 1280, 720
    if has_any_video:
        for t in downloaded_tracks:
            if t["has_video"]:
                d = t.get("details") or probe_media_stream_details(t["downloaded_path"])
                if d["width"] > 0 and d["height"] > 0:
                    target_w, target_h = d["width"], d["height"]
                    break

    # Step 3: Smart Segment Normalization (Parallel)
    async def _normalize_segment(item: dict) -> Tuple[int, str]:
        idx = item["idx"]
        dl_path = item["downloaded_path"]
        is_video = item["has_video"]
        track_title = item["title"]
        details = item.get("details") or probe_media_stream_details(dl_path)

        if has_any_video:
            # ── MERGE OUTPUT IS VIDEO (.mp4) ──────────────────────────────────
            tmp_seg = make_temp_filepath(f"_seg_{idx}.mp4")
            temp_files.append(tmp_seg)

            if is_video:
                cur_w = details["width"]
                cur_h = details["height"]
                has_audio = details["has_audio"]
                vcodec = details["vcodec"]
                acodec = details["acodec"]
                pix_fmt = details["pix_fmt"]
                fps = details["fps"]

                # Check if video is already 100% compatible for direct concatenation
                is_dimensions_match = (cur_w == target_w and cur_h == target_h)
                is_compatible_for_copy = (
                    is_dimensions_match
                    and vcodec in ["h264", "avc1"]
                    and pix_fmt == "yuv420p"
                    and abs(fps - 30.0) < 1.0
                    and (not has_audio or acodec in ["aac", "mp4a"])
                )

                if is_compatible_for_copy and has_audio:
                    # Fast Stream Copy: Zero CPU Re-encoding!
                    copy_cmd = [
                        FFMPEG_PATH, "-y",
                        "-i", dl_path,
                        "-c", "copy",
                        tmp_seg
                    ]
                    r = await loop.run_in_executor(
                        ffmpeg_thread_pool,
                        lambda: subprocess.run(copy_cmd, capture_output=True, text=True, timeout=60)
                    )
                    if r.returncode == 0 and os.path.exists(tmp_seg) and os.path.getsize(tmp_seg) > 1000:
                        return (idx, tmp_seg)

                # Re-encode only when required for aspect ratio / fps / audio harmonization
                if is_dimensions_match:
                    v_filter = "[0:v]setsar=1:1,fps=30,format=yuv420p[v]"
                else:
                    v_filter = (
                        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1,fps=30,format=yuv420p[v]"
                    )

                if has_audio:
                    norm_cmd = [
                        FFMPEG_PATH, "-y",
                        "-i", dl_path,
                        "-filter_complex",
                        f"{v_filter};[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a]",
                        "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", "-b:a", "192k",
                        "-shortest", tmp_seg
                    ]
                else:
                    norm_cmd = [
                        FFMPEG_PATH, "-y",
                        "-i", dl_path,
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-filter_complex", f"{v_filter}",
                        "-map", "[v]", "-map", "1:a",
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                        "-shortest", tmp_seg
                    ]

                await loop.run_in_executor(
                    ffmpeg_thread_pool,
                    lambda: subprocess.run(norm_cmd, capture_output=True, text=True, timeout=180)
                )

            else:
                # Audio track inside video merge: render black screen matching target orientation
                dur = details.get("duration", 30.0)
                if dur <= 0:
                    dur = 30.0

                render_cmd = [
                    FFMPEG_PATH, "-y",
                    "-f", "lavfi", "-i", f"color=c=black:s={target_w}x{target_h}:r=30:d={dur}",
                    "-i", dl_path,
                    "-filter_complex",
                    "[0:v]setsar=1:1,fps=30,format=yuv420p[v];"
                    "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a]",
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "200k",
                    "-c:a", "aac", "-b:a", "192k",
                    "-t", str(dur),
                    tmp_seg
                ]
                await loop.run_in_executor(
                    ffmpeg_thread_pool,
                    lambda: subprocess.run(render_cmd, capture_output=True, text=True, timeout=120)
                )

        else:
            # ── MERGE OUTPUT IS PURE AUDIO (.mp3) ─────────────────────────────
            tmp_seg = make_temp_filepath(f"_seg_{idx}.mp3")
            temp_files.append(tmp_seg)

            norm_aud_cmd = [
                FFMPEG_PATH, "-y",
                "-i", dl_path,
                "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                tmp_seg
            ]
            def _run_norm_audio():
                r = subprocess.run(norm_aud_cmd, capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    logger.error(f"Track {idx+1} audio norm failed (code {r.returncode}): {r.stderr}")

            await loop.run_in_executor(ffmpeg_thread_pool, _run_norm_audio)

        if not os.path.exists(tmp_seg) or os.path.getsize(tmp_seg) < 1000:
            raise Exception(f"Track {idx+1} ({track_title}) segment normalization failed.")

        return (idx, tmp_seg)

    segment_results = await asyncio.gather(*[_normalize_segment(item) for item in downloaded_tracks])
    segment_results.sort(key=lambda x: x[0])
    normalized_segments = [s[1] for s in segment_results if s[1] is not None]

    if len(normalized_segments) != len(downloaded_tracks):
        raise Exception("One or more selected tracks failed to normalize for concatenation.")

    # Step 4: Fast Sequential Concatenation (End-to-End Series Connection)
    seg_count = len(normalized_segments)
    unique_id = uuid.uuid4().hex[:8]
    timestamp = int(time.time())

    if has_any_video:
        media_type = "video/mp4"
        unique_filename = f"merged_remix_{timestamp}_{unique_id}.mp4"
    else:
        media_type = "audio/mpeg"
        unique_filename = f"merged_remix_{timestamp}_{unique_id}.mp3"

    output_merged = make_temp_filepath(f"_{unique_filename}")
    temp_files.append(output_merged)

    concat_cmd = [FFMPEG_PATH, "-y"]
    for seg in normalized_segments:
        concat_cmd.extend(["-i", seg])

    if seg_count == 1:
        if has_any_video:
            concat_cmd.extend(["-c:v", "copy", "-c:a", "copy", output_merged])
        else:
            concat_cmd.extend(["-c:a", "copy", output_merged])
    else:
        if has_any_video:
            filter_inputs = "".join([f"[{i}:v][{i}:a]" for i in range(seg_count)])
            filter_complex = f"{filter_inputs}concat=n={seg_count}:v=1:a=1[outv][outa]"
            concat_cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                output_merged
            ])
        else:
            filter_inputs = "".join([f"[{i}:a]" for i in range(seg_count)])
            filter_complex = f"{filter_inputs}concat=n={seg_count}:v=0:a=1[outa]"
            concat_cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[outa]",
                "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                output_merged
            ])

    def _run_concat():
        res = subprocess.run(concat_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg concat failed (code {res.returncode}): {res.stderr}")
            raise Exception(f"FFmpeg concatenation failed: {res.stderr}")

    await loop.run_in_executor(ffmpeg_thread_pool, _run_concat)

    if not os.path.exists(output_merged) or os.path.getsize(output_merged) == 0:
        raise Exception("Merged output file was not generated.")

    def stream_generator():
        with open(output_merged, "rb") as f:
            while chunk := f.read(65536):
                yield chunk
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    return stream_generator(), unique_filename, media_type
