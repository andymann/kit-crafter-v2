How to run it
python3 main.py

All its dependencies (pygame-ce, soundfile, pydub, numpy) are already installed on your system Python, so no venv/install step needed.

Optional: pass a folder to open it pre-loaded with your sample library:

python3 main.py "/path/to/your/samples"

Once a window opens, click any audio file in the browser — the BPM/Key fields in the detail pane at the bottom will fill in a moment later (analysis runs async, same pattern as waveform loading).
