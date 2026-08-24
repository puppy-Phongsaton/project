import tkinter as tk
import re
import ctypes

# เปลี่ยน Keyboard Layout เป็น English (US)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.LoadKeyboardLayoutW("00000409", 1)

def process_card(event=None):
    raw = entry.get().strip()

    entry.delete(0, tk.END)
    entry.focus_force()

    pattern = r"\^([^$]+)\$([^$]+)\$[^^]*\^\^(\d+)="

    m = re.search(pattern, raw)

    if m:
        lastname = m.group(1)
        firstname = m.group(2)
        cardid = m.group(3)[-13:]   # เอา 13 หลักสุดท้าย

        lbl_fname.config(text=firstname)
        lbl_lname.config(text=lastname)
        lbl_id.config(text=cardid)
    else:
        lbl_fname.config(text="ไม่พบข้อมูล")
        lbl_lname.config(text="-")
        lbl_id.config(text="-")

root = tk.Tk()
root.title("MSR90 Reader")
root.geometry("450x220")

tk.Label(root, text="ชื่อ", font=("Tahoma", 12)).pack(pady=(10,0))
lbl_fname = tk.Label(root, text="-", font=("Tahoma", 18))
lbl_fname.pack()

tk.Label(root, text="นามสกุล", font=("Tahoma", 12)).pack()
lbl_lname = tk.Label(root, text="-", font=("Tahoma", 18))
lbl_lname.pack()

tk.Label(root, text="เลขประจำตัว", font=("Tahoma", 12)).pack()
lbl_id = tk.Label(root, text="-", font=("Tahoma", 18))
lbl_id.pack()

# ช่องรับข้อมูล (ซ่อน)
entry = tk.Entry(root, width=1)
entry.place(x=-100, y=-100)
entry.bind("<Return>", process_card)

def keep_focus():
    entry.focus_force()
    root.after(500, keep_focus)

keep_focus()

root.mainloop()