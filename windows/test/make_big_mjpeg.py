"""a 4000 x 3000 MJPEG (grey stored as colour), 120 frames at 30 Hz, frame numbers written in: like a
widefield camera recording (decodes to 1.4 GB grey)"""
import av, numpy as np
from make_stream_data import code_frame
H, W, N = 3000, 4000, 120
rng = np.random.default_rng(1)
c = av.open('big_mjpeg_4k.avi', 'w'); s = c.add_stream('mjpeg', rate=30); s.width, s.height, s.pix_fmt = W, H, 'yuvj420p'
s.options = {'q:v': '3'}
for k in range(N):
    f = code_frame(k, H, W, rng)
    for p in s.encode(av.VideoFrame.from_ndarray(f, format='rgb24')): c.mux(p)
for p in s.encode(): c.mux(p)
c.close()
