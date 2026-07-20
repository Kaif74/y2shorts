# YouTube-to-Shorts Auto-Clipper

Sequential Python prototype that turns a YouTube URL into ranked,
vertical, captioned clips.

## Setup

1. Install **FFmpeg** and make `ffmpeg` available on your `PATH`.
2. Create and activate a virtual environment, then install Python packages:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Create a `.env` file in this project folder and add your Mistral key:

   ```dotenv
   MISTRAL_API_KEY=your-key
   $env:MISTRAL_API_KEY = "your-new-key" (powershell)

   ```

   The `.env` file is ignored by Git. You can alternatively set
   `MISTRAL_API_KEY` in PowerShell; that value takes precedence.

Faster-Whisper requires a CUDA-compatible CTranslate2 install to use the GTX 1650. The script first attempts `small` with `int8_float16` on CUDA, and falls
back to CPU `int8` with a warning if the GPU runtime is unavailable.

## Run

```powershell
python clip.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Local web UI

```powershell
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`, paste a YouTube link, and watch the live stage
timeline. The server keeps a session-only job history and serves completed clips
for preview and download. For another device on your home network, start with
`uvicorn app:app --host 0.0.0.0` and open your computer's LAN IP.

Useful options:

```powershell
python clip.py URL --max-clips 4 --min-duration 20 --max-duration 50
python clip.py URL --force-whisper --whisper-model base
python clip.py URL --crop-mode tracked
```

`tracked` currently preserves the v2 function interface and uses a centre crop;
face tracking is intentionally not included in this first end-to-end version.

Results are written to `output/<video_id>/` as MP4s named with their rank and
score, plus `rankings.json` containing titles, alternatives, reasons, and times.
Downloaded source files are reused under `downloads/<video_id>/`.

## Tuning

- Clip selection uses Mistral's `mistral-small-2603` chat model. Change
  `MISTRAL_MODEL` in `y2shorts/config.py` to use another compatible model.
- Caption transcripts are sent in 16,000-character chunks with a 2,000-
  character overlap to keep requests manageable for provider limits.
- Edit the clip-selection prompt in `y2shorts/config.py` to refine selection
  and titles.
- Edit `CAPTION_STYLE` in the same file to change typeface, size, position, or
  colours.
- Every stage is importable independently: transcript acquisition, LLM ranking,
  download, cropping, ASS creation, and burn-in live in their own modules.
