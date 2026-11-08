"""synthetic recordings with known truth: 10 % global rise in frames 41-60, local +50 % square, moving blob"""
import numpy as np, av, tifffile, scipy.io, h5py
rng = np.random.default_rng(1)
H, W, N, fps = 96, 128, 120, 20
yy, xx = np.mgrid[1:H+1, 1:W+1]
base = 80 + 40 * np.exp(-((xx - 64) ** 2 + (yy - 48) ** 2) / 2000)
fr = np.zeros((N, H, W))
for k in range(N):
    f = base.copy()
    if 40 <= k < 60: f *= 1.10
    if 70 <= k < 90: f[30:41, 50:66] *= 1.5          # rows 31-41, cols 51-66 (1-based)
    cx = 20 + k * 0.7
    f += 60 * np.exp(-((xx - cx) ** 2 + (yy - 70) ** 2) / 30)
    fr[k] = f + rng.normal(0, 1.0, (H, W))
fr8 = np.clip(np.rint(fr), 0, 255).astype(np.uint8)
np.save('truth_u8.npy', fr8)
# grey AVI (lossless FFV1) and MJPEG-in-AVI; colour MP4 (h264)
def write(path, codec, frames, pix, rgb=False):
    c = av.open(path, 'w'); s = c.add_stream(codec, rate=fps); s.width, s.height = W, H; s.pix_fmt = pix
    for f in frames:
        vf = av.VideoFrame.from_ndarray(f, format='rgb24' if rgb else 'gray')
        for p in s.encode(vf): c.mux(p)
    for p in s.encode(): c.mux(p)
    c.close()
write('grey_ffv1.avi', 'ffv1', fr8, 'gray')
write('grey_mjpeg.avi', 'mjpeg', np.repeat(fr8[..., None], 3, 3), 'yuvj420p', rgb=True)
col = np.stack([fr8, np.clip(fr8 * 0.5, 0, 255).astype(np.uint8), (255 - fr8)], 3)
write('colour_h264.mp4', 'libx264', col, 'yuv444p', rgb=True)
tifffile.imwrite('stack_u16.tif', (fr * 100).astype(np.uint16))
scipy.io.savemat('stack_v5.mat', {'movie': np.transpose(fr, (1, 2, 0)).astype(np.float32), 'small': np.zeros((2, 2, 2)), 'fps': 20.0})
with h5py.File('stack_v73.mat', 'w', userblock_size=512) as h:
    d = h.create_dataset('frames', data=fr8)            # MATLAB [H W N] is h5 [N W H]; store [N H W] -> transpose below
    del h['frames']
    d = h.create_dataset('frames', data=np.transpose(fr8, (0, 2, 1)))
    d.attrs['MATLAB_class'] = np.bytes_('uint8')
    f_ = h.create_dataset('fps', data=np.array([[20.0]])); f_.attrs['MATLAB_class'] = np.bytes_('double')
with open('stack_v73.mat', 'r+b') as fh:
    fh.write(b'MATLAB 7.3 MAT-file, Platform: GLNXA64, Created on: test HDF5 schema 1.00 .'.ljust(116, b' '))
print('ok')
