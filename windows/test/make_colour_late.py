"""colour recordings whose first frames are black or grey (a fade-in): they must stay in colour"""
import av, numpy as np, tifffile
H, W, N = 96, 128, 60
def frame(k):
    if k < 8:                                   # black, then grey: the first frames carry no colour
        g = np.full((H, W), 0 if k < 4 else 100, np.uint8)
        return np.stack([g, g, g], 2)
    f = np.zeros((H, W, 3), np.uint8)
    f[..., 0] = 200; f[..., 1] = (np.arange(W) * 2 % 256)[None, :]; f[..., 2] = 40
    return f
c = av.open('colour_fadein.mp4', 'w'); s = c.add_stream('libx264', rate=20); s.width, s.height, s.pix_fmt = W, H, 'yuv420p'
s.options = {'crf': '18'}
for k in range(N):
    for p in s.encode(av.VideoFrame.from_ndarray(frame(k), format='rgb24')): c.mux(p)
for p in s.encode(): c.mux(p)
c.close()
tifffile.imwrite('colour_fadein.tif', np.stack([frame(k) for k in range(N)]), photometric='rgb')
