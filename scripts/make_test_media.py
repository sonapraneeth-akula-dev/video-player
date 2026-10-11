"""Generate small, frame-indexed H.264 clips for playback tests."""

import subprocess
from pathlib import Path

MEDIA = Path(__file__).resolve().parents[1] / "tests" / "media"
FRAMES = 300
SIZE = "256x144"
INDEX = "geq=lum='if(lt(Y,16),if(bitand(N,pow(2,floor(X/16))),235,16),64)':cb=128:cr=128"


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


if __name__ == "__main__":
    generate()

