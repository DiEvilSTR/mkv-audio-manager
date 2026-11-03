# MKV Audio Manager

A small Python desktop app with an English interface. Browse a folder, select an MKV file, inspect its audio tracks, mark unwanted tracks and save a new MKV. You can also change the default audio track without removing anything.

## Run on Windows

Requires Python 3.10+ with Tkinter and FFmpeg (`ffmpeg` and `ffprobe`) on PATH. No Python packages need to be installed. Alternatively, put the FFmpeg executables in a `tools` folder beside `app.py`.

Double-click `start.bat`, or run `python app.py`.

1. Click **Open folder…** and select a folder containing MKV files.
2. Select a file on the left. Use the filename filter for large folders.
3. Click the **Remove** boxes beside unwanted audio tracks.
4. Optionally choose the audio track that should play by default. Players may override this with their own language preferences.
5. Leave **Overwrite original** checked to replace the selected file, or uncheck it to keep the original and save a sibling named `filename-clear.mkv`.
6. Click **Remove selected / Save MKV**.

**Overwrite original is enabled by default.** The app saves and verifies a temporary MKV in the same folder before replacing the source. After successful replacement, the removed tracks are no longer in the original file. Errors or cancellation before replacement leave the source untouched. If Windows cannot replace a locked file, close the player using it and retry.

With the checkbox off, results are saved beside the original as `filename-clear.mkv`. Existing copies are kept; repeated exports receive names such as `filename-clear (2).mkv`.

Video, remaining audio, subtitles, attachments, metadata and chapters are remuxed with stream copy, without re-encoding. Both modes require enough free disk space for a complete temporary output, even when replacing the original. Unsupported streams cause an error instead of being silently discarded. Files are processed individually; audio selections are not applied automatically to other episodes.

**Cancel** stops a save and removes the temporary output. Removing all audio asks for confirmation. With **Keep existing defaults**, a removed default track is not replaced automatically; choose a remaining track explicitly if desired.

## Verification

Run `python -m unittest discover -s tests -v`. Integration tests use local FFmpeg to generate tiny MKVs and verify stream removal, defaults, subtitles, attachments, chapters, metadata, cancellation, safe replacement and collision-safe copies.

## License

MKV Audio Manager is licensed under the [MIT License](LICENSE).

FFmpeg and FFprobe are external dependencies and are not included in this repository. They are covered by their own licenses; see [FFmpeg licensing information](https://ffmpeg.org/legal.html). The MIT License for this app does not replace the licenses of those tools.
