# Testing on the calculator

The automated tests (see [BUILDING.md](BUILDING.md)) prove that the calculator's decoder produces exactly the right pictures. They can't check the parts that only exist on a real fx-CG50: screens, keys, files and timing. This checklist covers those.

It's split into steps that match the commits, so if something breaks you can find which step caused it. To try an earlier step:

```bash
git checkout <commit>
```

```bash
make
```

When you're done, get back to the latest version:

```bash
git checkout improvements
```

## Step 0: new build tools, unchanged player

Commit: *Build setup for macOS and Linux, add-in icons*.

- [ ] `video_player.g3a` builds, and its new icon shows in the MENU.
- [ ] An existing `video.bin` plays exactly as before.

## Step 1: the converter

- [ ] Convert a video larger than 384×216 in the converter window. The calculator shows the same picture as the preview.
- [ ] With **Show advanced options → File type → Old player v2.0**, the file plays on the old player.
- [ ] The size estimate is close to the real file size.

## Step 2: new file format in the player

Commit: *Player: decode with the shared decoder, accurate timing, EXIT works*.

- [ ] The same video converted in both file types (each copied as `video.bin`) plays. The new type should be at least as smooth.
- [ ] A 29.97 fps video keeps time with a stopwatch over a minute, to within a second or so.
- [ ] EXIT during playback stops it.

## Step 3: player screens (latest version)

- [ ] With several `.bin` files, all of them show in the list with their titles and lengths.
- [ ] A `.bin` file that isn't a video shows as "(not a video)".
- [ ] With no `.bin` files, the "No videos found" help appears.
- [ ] The details screen shows the right size, frame rate and length.
- [ ] F1 toggles Loop, and a looping video starts again by itself.
- [ ] EXE during playback pauses and shows the progress bar and time.
- [ ] Pressing EXE again brings the picture back exactly: no leftover bar or text.
- [ ] EXIT stops playback and goes to the details screen. EXIT again goes to the list, and another video plays.
- [ ] At the end of a video, EXE plays it again without leaving the add-in.
- [ ] From the list, press MENU and open another app (e.g. RUN-MAT), then come back to VidPlayer: no "Bfile Error: -8", and videos still play.
- [ ] From the list, press MENU and go straight back to VidPlayer: it still works.
- [ ] Leave a video paused until the calculator switches itself off, then switch it on: it still works.

If something fails, note which item it was and what the screen showed.
