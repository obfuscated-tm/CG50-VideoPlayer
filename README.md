# CG50 Video Player

Play videos on a Casio **fx-CG50** graphing calculator. It should also work on the fx-CG10/20, but that hasn't been tested.

1. Convert a video on your computer with the **CG50 Video Converter**.
2. Copy the add-in and your videos to the calculator.
3. Pick a video from the list and press EXE.

## 1. Get the files

Download `video_player.g3a` and the converter for your computer from the [Releases](https://github.com/obfuscated-tm/CG50-VideoPlayer/releases) page.

To build them yourself instead, see [BUILDING.md](BUILDING.md). The latest build of every change is also on the repository's **Actions** tab, under **Artifacts**.

## 2. Convert a video

### With the converter window (easiest)

- **Windows:** unzip `CG50-Video-Converter-Windows.zip` and double-click **CG50 Video Converter.exe**. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**. The app isn't signed, so Windows doesn't recognize it.
- **Mac:** unzip `CG50-Video-Converter-macOS.zip`. The first time, **right-click** the app and choose **Open**, then **Open** again. The app isn't signed, so macOS asks once.
- **If you already have Python 3.9+:** double-click `Convert Video (Mac).command` or `Convert Video (Windows).bat` in this folder. The first run takes a minute to set itself up.

Then:

1. Click **Open video…** and pick a video (.mp4, .mov, .avi, …).
2. Choose your settings. The preview shows exactly what the calculator will show.

   | Setting | Tip |
   |---|---|
   | Picture size | **Recommended (128×72)** fills the screen and keeps files small. |
   | Frame rate | **15 fps** is smooth enough for most videos. |
   | Colors | **Best colors for this video** with 4–8 colors works well. Fewer colors make smaller files. |
   | Smoother shading | Makes gradients nicer, but files much bigger. |
   | Part of the video | Convert just a section, e.g. from `0:30` to `1:45`. |

3. Look at the **file size**. If it says the file is too big, click **Make it fit**.
4. Click **Convert**. The file is saved next to your video with a short name, e.g. `badapple.bin`.

### From a terminal

```bash
python3 -m pip install -r converter/requirements.txt
```

```bash
python3 converter/convert.py myvideo.mp4
```

```bash
python3 converter/convert.py myvideo.mp4 --size 192x108 --fps 20 --colors 8 --start 0:30 --end 1:45
```

Run `python3 converter/convert.py --help` to see every option.

## 3. Copy to the calculator

1. Connect the calculator with its USB cable. When the calculator asks, choose **USB Flash** (F1).
2. The calculator shows up as a drive. Copy `video_player.g3a` and your `.bin` videos into its **main folder**, not into a subfolder.
3. Eject the drive before you unplug the cable.

The fx-CG50 has about 16 MB of storage. At the recommended settings (128×72, 15 fps, 4 colors), a minute of video usually takes 0.3–0.8 MB. Busy scenes take more.

## 4. Play

Press **MENU** and open **VidPlayer**.

| Screen | Keys |
|---|---|
| Video list | **▲ ▼** choose, **EXE** open |
| Video details | **EXE** play, **F1** loop on/off, **EXIT** back to the list |
| Playing | **EXE** or **F1** pause, **EXIT** stop |
| Paused | shows how far along you are and the speed reached. **EXE** or **F1** continue, **EXIT** stop |
| End of the video | **EXE** play again, **EXIT** back |

To leave, press **MENU** on the list or details screen, like in any other app.

## Troubleshooting

- **"No videos found":** the `.bin` files must be in the calculator's main folder.
- **"(not a video)" in the list:** that `.bin` file isn't a video from the converter. Convert the video again.
- **"Bfile Error: -8":** a file was left open. Press the RESET button on the back of the calculator.
- **Choppy playback:** reading from storage is the calculator's slow part. Try a smaller picture size, fewer colors or a lower frame rate. The pause screen shows the speed actually reached.
- **The old player (v2.0.x) says "BAD VIDEO FILE":** files from the new converter need the new `video_player.g3a`. To make files for the old player, use **Show advanced options → File type → Old player v2.0**.

## How it works

- **Colors:** each video uses its own palette of 2–16 colors, in the calculator's 16-bit color format.
- **Scaling:** the picture is scaled up by a whole number so it fills as much of the 384×216 screen as possible.
- **Compression:** the new file format only stores what changed since the previous frame. Unchanged pixels cost nothing, which makes files 2–5 times smaller than the original format. The layout is described in [docs/FORMAT.md](docs/FORMAT.md).

## Building and testing

- [BUILDING.md](BUILDING.md): setting up the tools on Mac, Linux or Windows, and the automated tests.
- [TESTING.md](TESTING.md): checking a build on a real calculator.

## Credits

- Inspired by [oxixes/bad-apple-cg50](https://github.com/oxixes/bad-apple-cg50).
- Built with [libfxcg](https://github.com/Jonimoose/libfxcg). Syscall details are from [WikiPrizm](https://prizm.cemetech.net).
- The converter uses OpenCV, NumPy and Pillow.
