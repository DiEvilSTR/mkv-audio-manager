"""MKV inspection and lossless audio removal. No third-party Python packages."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable


class MediaError(Exception):
    pass


class Cancelled(MediaError):
    pass


def tool(name: str) -> str:
    local = Path(__file__).resolve().parent / "tools" / (name + ".exe" if os.name == "nt" else name)
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise MediaError(f"{name} was not found. Install FFmpeg and add its bin folder to PATH, "
                         "or place ffmpeg and ffprobe in the tools folder next to the app.")
    return found


def process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def inspect(path: Path) -> dict:
    try:
        result = subprocess.run(
            [tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-show_chapters",
             "-of", "json", str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, **process_options())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"Could not read {path.name}: {exc}") from exc
    if result.returncode:
        raise MediaError(result.stderr.strip() or "FFprobe could not read this file.")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise MediaError("FFprobe returned invalid metadata.") from exc


def audio_streams(info: dict) -> list[dict]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]


def export(path: Path, info: dict, remove: set[int], default: int | None,
           cancel: threading.Event, progress: Callable[[float], None], *,
           overwrite: bool = True) -> Path:
    """Verify a temporary remux, then replace the source or publish a sibling copy."""
    audio = audio_streams(info)
    indexes = {s["index"] for s in audio}
    if not remove <= indexes:
        raise MediaError("The selection contains a track that is not an audio track.")
    kept = [s for s in audio if s["index"] not in remove]
    if default is not None and default not in {s["index"] for s in kept}:
        raise MediaError("The default audio track must be a track you keep.")
    if not remove and default is None:
        raise MediaError("Select tracks to remove or choose a new default audio track.")
    if cancel.is_set():
        raise Cancelled("Operation cancelled.")
    ffmpeg = tool("ffmpeg")
    destination = path.parent
    fd, temporary = tempfile.mkstemp(prefix=".processing-", suffix=".mkv", dir=destination)
    os.close(fd)
    temp = Path(temporary)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(path), "-map", "0"]
    for index in sorted(remove):
        command += ["-map", f"-0:{index}"]
    command += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]
    # Explicitly preserve flags; FFmpeg otherwise may assign a default itself.
    for position, stream in enumerate(kept):
        flags = {key for key, value in stream.get("disposition", {}).items() if value}
        if default is not None:
            flags.discard("default")
            if stream["index"] == default:
                flags.add("default")
        command += [f"-disposition:a:{position}", "+".join(sorted(flags)) or "0"]
    command += ["-progress", "pipe:1", "-nostats", str(temp)]
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    process = None
    done = threading.Event()

    def watch_cancel():
        while not done.wait(0.1):
            if cancel.is_set():
                try:
                    process.terminate()
                except OSError:
                    pass
                return

    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                       text=True, encoding="utf-8", errors="replace",
                                       **process_options())
            watcher = threading.Thread(target=watch_cancel, daemon=True)
            watcher.start()
            for line in process.stdout:
                if line.startswith("out_time_us=") and duration:
                    try:
                        progress(min(99.0, max(0.0, int(line.split("=", 1)[1]) / duration / 10000)))
                    except ValueError:
                        pass
            process.stdout.close()
            code = process.wait()
            done.set()
            watcher.join()
            if cancel.is_set():
                raise Cancelled("Operation cancelled.")
            if code:
                errors.seek(0)
                raise MediaError(errors.read().decode("utf-8", errors="replace")[-6000:]
                                 or "FFmpeg could not save this file.")
        verified = inspect(temp)
        expected = [s.get("codec_type") for s in info["streams"] if s["index"] not in remove]
        if [s.get("codec_type") for s in verified["streams"]] != expected:
            raise MediaError("The output stream verification failed; no result was saved.")
        if cancel.is_set():
            raise Cancelled("Operation cancelled.")
        if overwrite:
            output = path
            os.replace(temp, output)
        else:
            # Publish without overwriting an existing sibling copy.
            number = 1
            while True:
                stem = f"{path.stem}-clear" if number == 1 else f"{path.stem}-clear ({number})"
                output = destination / f"{stem}{path.suffix}"
                try:
                    if os.name == "nt":
                        os.rename(temp, output)
                    else:
                        os.link(temp, output)
                    break
                except FileExistsError:
                    number += 1
        progress(100)
        return output
    finally:
        done.set()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        temp.unlink(missing_ok=True)
