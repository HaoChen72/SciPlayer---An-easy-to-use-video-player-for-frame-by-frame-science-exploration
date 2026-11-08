"""videos for the streaming tests: the frame number is written into every frame as 10 binary blocks"""
import numpy as np, av, sys
def code_frame(k, H, W, rng, colour=False):
    yy, xx = np.mgrid[0:H, 0:W]
    f = 90 + 50 * np.sin(xx / 97.0 + k / 15.0) * np.cos(yy / 71.0) + rng.normal(0, 3, (H, W))
    for b in range(10):                                   # bit b of k: block at x = b*80
        f[8:72, 8 + b * 80: 72 + b * 80] = 230 if (k >> b) & 1 else 25
    f = np.clip(f, 0, 255).astype(np.uint8)
    return np.stack([f, f, f], 2) if not colour else np.stack([f, (f * 0.7).astype(np.uint8), 255 - f], 2)
def read_code(fr):
    g = fr if fr.ndim == 2 else fr[..., 0]
    return sum(((g[20:60, 20 + b * 80: 60 + b * 80].mean() > 128) << b) for b in range(10))
def write(path, codec, N, H, W, fps, opts=None, pix='yuv420p', audio=False, colour=False):
    rng = np.random.default_rng(0)
    c = av.open(path, 'w')
    s = c.add_stream(codec, rate=fps); s.width, s.height, s.pix_fmt = W, H, pix
    if opts: s.options = opts
    a = None
    if audio:
        a = c.add_stream('aac', rate=48000); a.layout = 'stereo'
    t_audio = 0
    for k in range(N):
        vf = av.VideoFrame.from_ndarray(code_frame(k, H, W, rng, colour), format='rgb24')
        for p in s.encode(vf): c.mux(p)
        if a is not None:
            while t_audio < (k + 1) * 48000 // fps:      # a 440 Hz tone whose loudness steps every second
                n = 1024; t = (t_audio + np.arange(n)) / 48000.0
                amp = 0.1 + 0.2 * ((t.astype(int)) % 2)
                x = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
                af = av.AudioFrame.from_ndarray(np.stack([x, x]), format='fltp', layout='stereo'); af.sample_rate = 48000
                af.pts = t_audio
                for p in a.encode(af): c.mux(p)
                t_audio += n
    for p in s.encode(): c.mux(p)
    if a is not None:
        for p in a.encode(): c.mux(p)
    c.close()
if __name__ == '__main__':
    write('hd_h264_gop250_audio.mp4', 'libx264', 400, 1080, 1920, 30, {'preset': 'veryfast', 'bf': '3', 'g': '250', 'crf': '20'}, audio=True)
    write('hd_h264_gop250_colour.mkv', 'libx264', 300, 720, 1280, 25, {'preset': 'veryfast', 'bf': '3', 'g': '120', 'crf': '18'}, colour=True)
    write('mjpeg_allintra.avi', 'mjpeg', 200, 480, 800, 20, {'q:v': '2'}, pix='yuvj420p')
    print('ok')
