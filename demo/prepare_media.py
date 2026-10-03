"""Make controllable MP4 derivatives of the existing captioned WebP replays.

Run with the repository's Pillow environment: .venv/bin/python demo/prepare_media.py
Requires ffmpeg on PATH. No frames are added, dropped, cropped, or re-timed.
The original WebP files remain the source assets.
"""

from pathlib import Path
import subprocess
import sys

from PIL import Image


ASSETS = Path(__file__).resolve().parent / "assets"

sources = [Path(name).resolve() for name in sys.argv[1:]] if len(sys.argv) > 1 else sorted(ASSETS.glob("*-s*-*.webp"))
for source in sources:
    if source.stem.endswith("-poster"):
        continue
    with Image.open(source) as animation:
        animation.seek(0)
        animation.load()
        # The poster is an exact, losslessly encoded copy of the initial frame.
        animation.convert("RGB").save(source.with_name(source.stem + "-poster.webp"), lossless=True)
        width, height = animation.size
        frame_duration = animation.info["duration"]
        command = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
            "-framerate", f"1000/{frame_duration}", "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-video_track_timescale", "1000000", str(source.with_suffix(".mp4")),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            for index in range(animation.n_frames):
                animation.seek(index)
                animation.load()
                duration = animation.info["duration"]
                assert duration % frame_duration == 0, "Unexpected variable frame duration"
                frame = animation.convert("RGB").tobytes()
                # WebP coalesces identical adjacent frames; expand only those holds.
                for _ in range(duration // frame_duration):
                    process.stdin.write(frame)
        finally:
            process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError(f"Failed to encode {source.name}")
        print(f"Prepared {source.with_suffix('.mp4').name}")
