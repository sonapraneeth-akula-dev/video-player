"""Generate frame-indexed playback fixtures and a small codec/container matrix."""

import argparse
import random
import subprocess
import tempfile
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
CORRUPT_SOURCES = (
    ("matrix_h264_mp4.mp4", "mkv"),
    ("matrix_hevc_mkv.mkv", "avi"),
    ("matrix_vp9_webm.webm", "mp4"),
    ("matrix_av1_mp4.mp4", "webm"),
    ("matrix_aac_mp4.mp4", "mkv"),
)


def passthrough_sync() -> tuple[str, str]:
    options = subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-h", "full"], text=True, stderr=subprocess.STDOUT,
    )
    if "-fps_mode" in options:
        return "-fps_mode", "passthrough"
    if "-vsync" in options:
        return "-vsync", "0"
    raise RuntimeError("FFmpeg has no passthrough video sync option")


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
                *passthrough_sync(), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-qp", "0",
                "-g", "250", "-keyint_min", "250", "-sc_threshold", "0",
                str(directory / name),
            ],
            check=True,
        )

    generate_vfr(directory)
    generate_multitrack(directory)
    generate_snapshot_edge_cases(directory)

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


def generate_vfr(directory: Path = MEDIA) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "h264_vfr.mkv"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"nullsrc=s={SIZE}:r=60",
            "-frames:v", "90",
            "-vf", f"{INDEX},setpts='3*floor(N/2)+2*mod(N,2)'",
            *passthrough_sync(), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-qp", "0",
            "-g", "250", "-keyint_min", "250", "-sc_threshold", "0",
            str(target),
        ],
        check=True,
    )
    return target


def generate_4k_backstep(directory: Path = MEDIA) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "hevc_4k_gop250.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=25",
            "-f", "lavfi", "-i", f"nullsrc=s={SIZE}:r=25",
            "-frames:v", str(FRAMES),
            "-filter_complex", f"[1:v]{INDEX}[index];[0:v][index]overlay=0:0:shortest=1",
            "-c:v", "libx265", "-preset", "ultrafast",
            "-x265-params", "log-level=error:pools=none",
            "-pix_fmt", "yuv420p", "-crf", "18",
            "-g", "250", "-keyint_min", "250", "-sc_threshold", "0",
            str(target),
        ],
        check=True,
    )
    return target


def generate_snapshot_edge_cases(directory: Path = MEDIA) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    hdr_filter = (
        "zscale=transferin=bt709:matrixin=bt709:primariesin=bt709:"
        "transfer=smpte2084:matrix=bt2020nc:primaries=bt2020,format=yuv420p10le"
    )
    rotation_option = "-display_rotation" in subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-h", "full"], text=True, stderr=subprocess.STDOUT,
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            *(["-display_rotation", "90"] if rotation_option else []),
            "-i", str(directory / "h264_25.mp4"), "-t", "1", "-c:v", "copy",
            *([] if rotation_option else ["-metadata:s:v:0", "rotate=90"]),
            str(directory / "h264_rotated.mp4"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x800000:s=256x144:r=25:d=1",
            "-vf", hdr_filter,
            "-c:v", "libx265", "-preset", "ultrafast",
            "-x265-params", "log-level=error:pools=none",
            "-color_primaries", "bt2020", "-color_trc", "smpte2084",
            "-colorspace", "bt2020nc", str(directory / "hevc_hdr_pq.mp4"),
        ],
        check=True,
    )


def generate_multitrack(directory: Path = MEDIA) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    external = directory / "tracks_external.srt"
    external.write_text(
        "1\n00:00:00,300 --> 00:00:02,200\nExternal subtitle\n",
        encoding="utf-8",
    )
    target = directory / "tracks_multi.mkv"
    with tempfile.TemporaryDirectory() as temporary:
        alternate = Path(temporary) / "alternate.srt"
        alternate.write_text(
            "1\n00:00:00,500 --> 00:00:02,400\nAlternate subtitle\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=256x144:r=25:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=3",
                "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:d=3",
                "-i", str(external), "-i", str(alternate),
                "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map", "4:s",
                "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=fra",
                "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=fra",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-c:s", "srt", "-shortest", str(target),
            ],
            check=True,
        )
    return target


def generate_corrupt(directory: Path = MEDIA, seed: int = 20261011) -> None:
    rng = random.Random(seed)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(50):
        source, wrong_ext = CORRUPT_SOURCES[index % len(CORRUPT_SOURCES)]
        data = bytearray((MEDIA / source).read_bytes())
        kind = ("truncated", "flipped", "wrong_extension")[index % 3]
        ext = wrong_ext if kind == "wrong_extension" else Path(source).suffix[1:]
        if kind == "truncated":
            data = data[:rng.randrange(256, len(data))]
        elif kind == "flipped":
            for _ in range(rng.randint(1, 16)):
                offset = rng.randrange(256, len(data))
                data[offset] ^= rng.randint(1, 255)
        (directory / f"corrupt_{index:02}_{kind}.{ext}").write_bytes(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    variant = parser.add_mutually_exclusive_group()
    variant.add_argument("--corrupt", action="store_true")
    variant.add_argument("--backstep", action="store_true")
    args = parser.parse_args()
    if args.corrupt:
        generate_corrupt()
    elif args.backstep:
        generate_4k_backstep()
    else:
        generate()
