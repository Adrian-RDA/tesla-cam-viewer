# TeslaCam Viewer

A modern, GPU-accelerated dashcam viewer for Tesla SavedClips footage on Windows.

## Features

- **4-camera grid** — Front, Back, Left and Right Repeater in a live NVR-style view
- **Seamless playback** — automatic clip-to-clip transitions across 1-minute segments
- **Synchronised cameras** — all four streams stay in lock-step (< 250 ms drift tolerance)
- **Event timeline** — scrubber with a red marker at the exact event trigger timestamp
- **Event list** — sidebar with thumbnail, location, trigger reason and duration
- **Speed control** — ¼×, ½×, 1×, 1.5×, 2×, 4× playback
- **Maximise** any camera with a double-click; restore with another double-click
- **OLED dark UI** — deep black palette with Tesla-red accent (#E31937)
- **GPU acceleration** — via Qt Multimedia / Windows Media Foundation (D3D11/D3D12)

## Requirements

- Windows 10/11 (64-bit)
- A Tesla `SavedClips` folder (USB drive or copied locally)

No Python installation required for the distributed `.exe`.

## Download

Download the latest release from the [Releases](../../releases) page and unzip.  
Run `TeslaCamViewer.exe` — no installer needed.

## Usage

1. Launch `TeslaCamViewer.exe`
2. The app auto-loads `D:\TeslaCam\SavedClips` if it exists
3. Or click **Ordner öffnen** to select your SavedClips folder
4. Click an event in the sidebar to load it
5. Use the timeline controls to scrub, play, and change speed

## Development Setup

```powershell
# Clone and install dependencies
git clone https://github.com/nexave/tesla-cam-viewer.git
cd tesla-cam-viewer
python -m pip install -r requirements-build.txt

# Run from source
python main.py

# Build standalone executable
.\build.ps1
# Output: dist\TeslaCamViewer\TeslaCamViewer.exe
```

## Building

The build script handles everything automatically:

```powershell
.\build.ps1          # standard build
.\build.ps1 -Clean   # clean previous artifacts first
```

Requires Python 3.11+ and the packages in `requirements-build.txt`.

## Project Structure

```
tesla-cam-viewer/
├── main.py                  # entry point
├── core/
│   ├── event.py             # TeslaEvent dataclass + MP4 parser
│   ├── scanner.py           # async folder scanner (QThreadPool)
│   └── sync_controller.py   # 4-player sync engine (QTimer)
├── ui/
│   ├── main_window.py       # main window + header bar
│   ├── grid_view.py         # 2×2 grid / single-camera view
│   ├── player_widget.py     # individual camera player (QMediaPlayer)
│   ├── event_list.py        # sidebar event list + cards
│   ├── timeline.py          # scrubber, transport buttons, speed control
│   ├── spinner.py           # buffering overlay animation
│   └── icons.py             # inline SVG icon renderer
└── resources/
    ├── style.qss            # OLED dark theme
    └── icon.png             # app icon (1024×1024)
```

## License

MIT
