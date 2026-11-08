"""an uncompressed grey-as-BGR AVI over 1 GB (OpenDML, several RIFF segments), frame numbers written in"""
import av, numpy as np, sys
from make_stream_data import code_frame
H, W, N = 760, 1250, 420
rng = np.random.default_rng(0)
c = av.open('raw_bgr_big.avi', 'w'); s = c.add_stream('rawvideo', rate=30); s.width, s.height, s.pix_fmt = W, H, 'bgr24'
for k in range(N):
    f = code_frame(k, H, W, rng)
    for p in s.encode(av.VideoFrame.from_ndarray(f, format='rgb24')): c.mux(p)
for p in s.encode(): c.mux(p)
c.close()
