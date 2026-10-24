import sys, os, tkinter as tk
sys.path.insert(0, os.path.dirname(__file__))
from ui.app_window import AppWindow
root = tk.Tk()
app = AppWindow(root)
if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
    app._browser.set_library_root(sys.argv[1])
    app._path_lbl.configure(text=sys.argv[1])
root.mainloop()
