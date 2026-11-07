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
for index, (label, path) in enumerate(panel.entries):
    panel.choice.SetSelection(index)
    t = time.perf_counter()
    panel._load()
    prep = (time.perf_counter() - t) * 1000
    scene = panel._scene
    items = len(scene.items) if scene else 0
    segs = sum(len(seg) + 1 for item, *_ in (scene.items if scene else []) for _, _, seg in item.paths)
    fit_ms = snapshot("preview_{:02d}_fit".format(index))
    # glide in by 4 notches around the centre, timing every frame
    w, h = panel.canvas.GetClientSize()
    panel.on_wheel(NS(GetPosition=lambda: (w // 3, h // 2), GetWheelRotation=lambda: 480, GetWheelDelta=lambda: 120))
    frames = []
    while panel._anim.IsRunning():
        time.sleep(0.01)
        panel.on_frame(None)
        frames.append(paint_ms())
    zoom_ms = snapshot("preview_{:02d}_zoom".format(index))
    panel.on_press(NS(GetPosition=lambda: (200, 200)))
    drags = []
    for k in range(20):
        panel.on_motion(NS(GetPosition=lambda: (200 - 10 * k, 200 - 5 * k), Dragging=lambda: True))
        drags.append(paint_ms())
    panel.on_release(None)
    print("  {:<40} prep {:6.0f} ms, {:5d} items, {:7d} segments | paint fit {:5.1f} ms, "
          "zoom frames {} avg {:5.1f} max {:5.1f} ms, drag avg {:5.1f} ms".format(
              label[:40], prep, items, segs, fit_ms, len(frames),
              sum(frames) / max(len(frames), 1), max(frames or [0]), sum(drags) / len(drags)))
    panel.fit()

dlg.SetSize(wx.Size(1300, 800))
panel.choice.SetSelection(0)
panel._load()
wx.Yield()
dlg.Destroy()
