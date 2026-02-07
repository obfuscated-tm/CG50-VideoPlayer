import cv2
import struct
import numpy as np
import os
import sys
from sklearn.cluster import KMeans

def process_video(input_path):
    video = cv2.VideoCapture(input_path)
    if not video.isOpened(): return

    W, H, TARGET_FPS = 128, 64, 15
    PALETTE_SIZE = 32 
    
    print("Analyzing video for  32-color palette (may take a while)")
    samples = []
    # Sample 100 random frames to get a representative palette
    for _ in range(100):
        video.set(cv2.CAP_PROP_POS_FRAMES, np.random.randint(0, video.get(cv2.CAP_PROP_FRAME_COUNT)))
        ok, frame = video.read()
        if ok:
            samples.append(cv2.resize(frame, (32, 16)).reshape(-1, 3))
    
    data = np.concatenate(samples)
    kmeans = KMeans(n_clusters=PALETTE_SIZE, n_init=10).fit(data)
    palette_bgr = kmeans.cluster_centers_.astype(np.uint16)
    
    # Convert BGR palette to RGB565
    palette_565 = []
    for bgr in palette_bgr:
        b, g, r = bgr[0], bgr[1], bgr[2]
        p565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        palette_565.append(p565)

    video.set(cv2.CAP_PROP_POS_FRAMES, 0)
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))

    with open("video.bin", "wb") as f:
        f.write(struct.pack(">IHHHB", total_frames, W, H, TARGET_FPS, PALETTE_SIZE))
        for p in palette_565:
            f.write(struct.pack(">H", p))

        while True:
            ok, frame = video.read()
            if not ok: break
            
            # Simple resize, no boosting
            resized = cv2.resize(frame, (W, H))
            pixels = kmeans.predict(resized.reshape(-1, 3)).astype(np.uint8)

            rle_data = []
            curr_idx, run_len = pixels[0], 0
            for p in pixels:
                if p == curr_idx and run_len < 255:
                    run_len += 1
                else:
                    rle_data.append(struct.pack("BB", run_len, curr_idx))
                    curr_idx, run_len = p, 1
            rle_data.append(struct.pack("BB", run_len, curr_idx))

            encoded_frame = b"".join(rle_data)
            f.write(struct.pack(">I", len(encoded_frame)))
            f.write(encoded_frame)

    video.release()
    print(f"Natural 32-Color Video Done! Size: {os.path.getsize('video.bin')/1024:.1f} KB")

if __name__ == "__main__":
    process_video(sys.argv[1] if len(sys.argv) > 1 else "input.mp4")