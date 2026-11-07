"""Open the real settings window (wxPython, under Xvfb in CI), generate the
G-code for a board, then exercise the preview: every image, zooming and
dragging, with paint times. Writes PNG snapshots of the preview.

    xvfb-run python3 tests/e2e/gui_check.py BOARD OUT_DIR
"""

import os
import sys
import time
from types import SimpleNamespace as NS

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "plugin"))

import wx  # noqa: E402

from kicad_pcb2gcode import gui, i18n  # noqa: E402
from kicad_pcb2gcode.app import BoardContext  # noqa: E402
from kicad_pcb2gcode.settings import load_board_settings, load_config  # noqa: E402

board, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(out_dir, exist_ok=True)
i18n.set_lang("de")
print("wxPython", wx.version(), "svg:", gui.HAVE_SVG)

app = wx.App(False)
cfg = load_config()
ctx = BoardContext(board_path=board)
dlg = gui.Pcb2GcodeDialog(None, ctx, load_board_settings(cfg, board), cfg)
dlg.Show()
done = []
original_finished = dlg._finished


def finished(*args):
    original_finished(*args)
    done.append(args[1])


dlg._finished = finished
wx.MessageBox = lambda *a, **k: print("MessageBox:", a[0])
dlg.on_generate(None)
start = time.time()
while not done and time.time() - start < 300:
    wx.Yield()
    time.sleep(0.02)
print("---- log ----")
print(dlg.log_ctrl.GetValue())
print("error:", done[0] if done else "timeout")

panel = dlg.preview
print("---- preview images ----")
for label, path in panel.entries:
    print(" ", label, "->", os.path.relpath(path, ctx.output_dir(dlg.read_form()[0])))


def snapshot(name):
    w, h = panel.canvas.GetClientSize()
    bmp = wx.Bitmap(w, h)
    mdc = wx.MemoryDC(bmp)
    t = time.perf_counter()
    panel.draw(mdc, w, h)
    ms = (time.perf_counter() - t) * 1000
    mdc.SelectObject(wx.NullBitmap)
    bmp.SaveFile(os.path.join(out_dir, name + ".png"), wx.BITMAP_TYPE_PNG)
    return ms


def paint_ms():
    w, h = panel.canvas.GetClientSize()
    bmp = wx.Bitmap(w, h)
    mdc = wx.MemoryDC(bmp)
    t = time.perf_counter()
    panel.draw(mdc, w, h)
    ms = (time.perf_counter() - t) * 1000
    mdc.SelectObject(wx.NullBitmap)
    return ms


print("---- preview drawing (canvas {}x{}) ----".format(*panel.canvas.GetClientSize()))


class Idle:
    def RequestMore(self, more=True):
        self.more = True


def idle_until_done(limit_s=20.0):
    t = time.perf_counter()
    while time.perf_counter() - t < limit_s:
        ev = Idle()
        ev.more = False
        panel.on_idle(ev)
        if not ev.more:
            break
    return (time.perf_counter() - t) * 1000


def stats(xs):
    return "avg {:5.1f} max {:5.1f}".format(sum(xs) / max(len(xs), 1), max(xs or [0]))


for index, (label, path) in enumerate(panel.entries):
    panel.choice.SetSelection(index)
    t = time.perf_counter()
    panel._load()
    prep = (time.perf_counter() - t) * 1000
    w, h = panel.canvas.GetClientSize()
    first = snapshot("preview_{:02d}_fit".format(index))
    heavy = panel._heavy
    prefetch = idle_until_done()
    rest = paint_ms()
    # glide in by 4 notches; one idle step between frames, as in the event loop
    panel.on_wheel(NS(GetPosition=lambda: (w // 3, h // 2), GetWheelRotation=lambda: 480, GetWheelDelta=lambda: 120))
    frames = []
    k = 0
    while panel._anim.IsRunning():
        time.sleep(0.01)
        panel.on_frame(None)
        if k == 3:
            frames.append(snapshot("preview_{:02d}_glide".format(index)))
        else:
            frames.append(paint_ms())
        k += 1
        ev = Idle()
        ev.more = False
        panel.on_idle(ev)
    settle = snapshot("preview_{:02d}_zoom".format(index))
    idle_until_done()
    panel.on_press(NS(GetPosition=lambda: (200, 200)))
    drags = []
    for k in range(20):
        panel.on_motion(NS(GetPosition=lambda: (200 - 10 * k, 200 - 5 * k), Dragging=lambda: True))
        drags.append(paint_ms())
    panel.on_release(None)
    print("  {:<32} prep {:5.0f} ms | first {:6.1f} ms {} prefetch {:6.0f} ms rest {:5.1f} | "
          "glide {} frames {} | settle {:6.1f} | drag {}".format(
              label[:32], prep, first, "HEAVY" if heavy else "light", prefetch, rest, len(frames),
              stats(frames), settle, stats(drags)))
    panel.fit()

dlg.SetSize(wx.Size(1300, 800))
panel.choice.SetSelection(0)
panel._load()
wx.Yield()
dlg.Destroy()
