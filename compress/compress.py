import cv2
import struct
import numpy as np
import os
import sys

# --- PALETTE DEFINITIONS ---

PALETTES = {
    "1": ("Standard 16-Color", np.array([
        [0, 0, 0], [128, 0, 0], [0, 128, 0], [128, 128, 0],
        [0, 0, 128], [128, 0, 128], [0, 128, 128], [192, 192, 192],
        [128, 128, 128], [255, 0, 0], [0, 255, 0], [255, 255, 0],
        [0, 0, 255], [255, 0, 255], [0, 255, 255], [255, 255, 255]
    ], dtype=np.uint8)),
    
    "2": ("4-Color Grayscale (GameBoy)", np.array([
        [0, 0, 0], [85, 85, 85], [170, 170, 170], [255, 255, 255]
    ], dtype=np.uint8)),
    
    "3": ("16-Level Grayscale", np.array([
        [i, i, i] for i in np.linspace(0, 255, 16).astype(np.uint8)
    ], dtype=np.uint8)),
    
    "4": ("High-Contrast B&W (2-Color)", np.array([
        [0, 0, 0], [255, 255, 255]
    ], dtype=np.uint8))
}

def select_palette():
    print("\n--- Select Video Palette ---")
    for key, (name, _) in PALETTES.items():
        print(f"{key}: {name}")
    
    choice = input("\nEnter choice (1-4): ").strip()
    if choice not in PALETTES:
        print("Invalid choice, defaulting to Standard 16-Color.")
        return PALETTES["1"][1]
    
    return PALETTES[choice][1]

# Global variable to be set at runtime
FIXED_PALETTE_BGR = None

def get_palette_565():
    palette_565 = []
    for bgr in FIXED_PALETTE_BGR:
        # Convert BGR to RGB565
        b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
        p565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        palette_565.append(p565)
    return palette_565

def process_video(input_path):
    global FIXED_PALETTE_BGR
    FIXED_PALETTE_BGR = select_palette()
    
    video = cv2.VideoCapture(input_path)
    if not video.isOpened():
        print("Error: Could not open video.")
        return

    W = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    FPS = int(video.get(cv2.CAP_PROP_FPS))
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))

    if W > 384 or H > 216:
        print(f"FATAL ERROR: Resolution {W}x{H} exceeds 384x216.")
        video.release()
        sys.exit(1)

    palette_565 = get_palette_565()
    pal_size = len(palette_565)

    print(f"\nEncoding {W}x{H} @ {FPS} FPS with {pal_size} colors")

    with open("video.bin", "wb") as f:
        # Header: Frames(4), W(2), H(2), FPS(2), PalSize(1)
        f.write(struct.pack(">IHHHB", total_frames, W, H, FPS, pal_size))
        for p in palette_565:
            f.write(struct.pack(">H", p))

        frame_idx = 0
        while True:
            ok, frame = video.read()
            if not ok: break
            
            pixels = frame.reshape(-1, 3).astype(np.int32)
            
            # Find closest colors in selected palette
            distances = np.sum((pixels[:, np.newaxis] - FIXED_PALETTE_BGR)**2, axis=2)
            pixel_indices = np.argmin(distances, axis=1).astype(np.uint8)

            # Run-Length Encoding
            rle_data = []
            if len(pixel_indices) > 0:
                curr_val, run_len = pixel_indices[0], 0
                for p in pixel_indices:
                    if p == curr_val and run_len < 255:
                        run_len += 1
                    else:
                        rle_data.append(struct.pack("BB", run_len, curr_val))
                        curr_val, run_len = p, 1
                rle_data.append(struct.pack("BB", run_len, curr_val))

            encoded = b"".join(rle_data)
            f.write(struct.pack(">I", len(encoded)))
            f.write(encoded)
            
            frame_idx += 1
            if frame_idx % 10 == 0:
                print(f"Progress: {frame_idx}/{total_frames} frames", end="\r")

    video.release()
    print(f"\nDone! Final Size: {os.path.getsize('video.bin')/1024:.1f} KB")

if __name__ == "__main__":
    process_video(sys.argv[1] if len(sys.argv) > 1 else "input.mp4")