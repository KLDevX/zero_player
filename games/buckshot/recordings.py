"""MP4 videos of the record runs the bridge kept (reports/ui/recordings/record_<N>r_<date>/).

    python -m games.buckshot.recordings            # make the MP4 for every kept run that has none yet
    python -m games.buckshot.recordings <folder>   # one folder (e.g. a `record test` run)

A kept run is a folder of game frames (JPG), times.txt (frame name, milliseconds since the run began) and
sound.wav (the game's sound, recorded from its Master bus). Each frame is shown for as long as it really was
on screen, so the picture stays in step with the sound: the ×20 parts play fast, the slowed record part plays
at normal speed. The video goes next to the folder as record_<N>r_<date>.mp4; older record videos are removed
(only the record is kept, Akel). Needs tools/ffmpeg/ffmpeg.exe (ffmpeg 9.0.2 essentials, gyan.dev).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(__file__).resolve().parent  # games/buckshot: its models, reports, docs, game copy
REC = GAME / "reports" / "ui" / "recordings"
FFMPEG = ROOT / "tools" / "ffmpeg" / "ffmpeg.exe"


def make_mp4(folder: Path) -> Path:
    times = [line.split() for line in (folder / "times.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = []
    for k, (name, ms) in enumerate(times):
        nxt = int(times[k + 1][1]) if k + 1 < len(times) else int(ms) + 250
        lines += [f"file '{name}'", f"duration {max(1, nxt - int(ms)) / 1000:.3f}"]
    lines.append(f"file '{times[-1][0]}'")  # the concat format needs the last frame twice
    listing = folder / "frames.txt"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = folder.parent / f"{folder.name}.mp4"
    cmd = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing)]
    if (folder / "sound.wav").exists():
        cmd += ["-i", str(folder / "sound.wav"), "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-vf", "scale=1920:1080:flags=neighbor,format=yuv420p", "-c:v", "libx264", "-crf", "28",
            "-preset", "veryfast", "-fps_mode", "vfr", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not FFMPEG.exists():
        sys.exit(f"no {FFMPEG}")
    if len(sys.argv) > 1:
        print(make_mp4(Path(sys.argv[1])))
        return
    folders = sorted((p for p in REC.glob("record_*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for folder in folders:
        out = folder.parent / f"{folder.name}.mp4"
        if not out.exists():
            print("making", out.name)
            make_mp4(folder)
        shutil.rmtree(folder)  # the frames are in the video now
    if folders:
        newest = folders[-1].name + ".mp4"  # the newest kept run is the record
        for old in REC.glob("record_*.mp4"):
            if old.name != newest:
                old.unlink()
                print("removed the old record video", old.name)


if __name__ == "__main__":
    main()
