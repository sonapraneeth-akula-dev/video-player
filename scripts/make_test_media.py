"""Generate frame-indexed playback fixtures and a small codec/container matrix."""

import subprocess
from pathlib import Path

MEDIA = Path(__file__).resolve().parents[1] / "tests" / "media"
FRAMES = 300
SIZE = "256x144"
INDEX = "geq=lum='if(lt(Y,16),if(bitand(N,pow(2,floor(X/16))),235,16),64)':cb=128:cr=128"
VIDEO_CONTAINERS = {
    "h264": ("mp4", "mkv", "mov", "avi", "ts"),
    "hevc": ("mp4", "mkv", "mov", "ts"),
    "vp9": ("mp4", "mkv", "webm", "avi"),
    "av1": ("mp4", "mkv", "webm", "avi"),
}
VIDEO_ENCODERS = {
    "h264": ("libx264", "-preset", "ultrafast"),
    "hevc": ("libx265", "-preset", "ultrafast", "-x265-params", "log-level=error:pools=none"),
    "vp9": ("libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"),
    "av1": ("libaom-av1", "-cpu-used", "8"),
}
AUDIO_ENCODERS = {
    "aac": "aac",
    "mp3": "libmp3lame",
    "opus": "libopus",
    "ac3": "ac3",
}
CONTAINER_AUDIO = {"mp4": "aac", "mkv": "aac", "mov": "aac", "avi": "mp3", "ts": "aac", "webm": "opus"}
AUDIO_CONTAINERS = {"aac": "mp4", "mp3": "mp3", "opus": "ogg", "ac3": "ac3"}


def generate(directory: Path = MEDIA) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for rate, name, offset in (
        ("25", "h264_25.mp4", False),
        ("30000/1001", "h264_30000-1001.mp4", False),
        ("60", "h264_60.mp4", False),
        ("25", "h264_25_start2.mkv", True),
    ):
        filters = f"{INDEX},setpts=PTS+2/TB" if offset else INDEX
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"nullsrc=s={SIZE}:r={rate}",
                "-frames:v", str(FRAMES), "-vf", filters,
                "-fps_mode", "passthrough", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-qp", "0",
                "-g", "250", "-keyint_min", "250", "-sc_threshold", "0",
                str(directory / name),
            ],
            check=True,
        )

    for codec, containers in VIDEO_CONTAINERS.items():
        for ext in containers:
            audio = CONTAINER_AUDIO[ext]
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "nullsrc=s=96x64:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "1", "-map", "0:v", "-map", "1:a",
                    "-vf", INDEX, "-pix_fmt", "yuv420p",
                    "-c:v", *VIDEO_ENCODERS[codec], "-threads", "2",
                    "-c:a", AUDIO_ENCODERS[audio], "-b:a", "96k",
                    str(directory / f"matrix_{codec}_{ext}.{ext}"),
                ],
                check=True,
            )

    for audio, native_ext in AUDIO_CONTAINERS.items():
        for ext in ("mkv", native_ext):
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "1", "-c:a", AUDIO_ENCODERS[audio], "-b:a", "96k",
                    str(directory / f"matrix_{audio}_{ext}.{ext}"),
                ],
                check=True,
            )


if __name__ == "__main__":
    generate()
