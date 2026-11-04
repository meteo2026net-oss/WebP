import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xarray as xr


class GribExplorerApp:

  def __init__(self, root):
    self.root = root
    self.root.title("مستكشف ملفات الأرصاد الجوية (GRIB Viewer)")
    self.root.geometry("850x650")

    # تحسين مظهر الواجهة
    style = ttk.Style()
    style.theme_use("clam")

    # --- الجزء العلوي: اختيار الملف ---
    top_frame = ttk.LabelFrame(root, text=" اختيار الملف ", padding=10)
    top_frame.pack(fill="x", padx=10, pady=5)

    self.file_path_var = tk.StringVar()
    file_entry = ttk.Entry(
        top_frame, textvariable=self.file_path_var, font=("Segoe UI", 10)
    )
    file_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

    btn_browse = ttk.Button(
        top_frame, text="استعراض...", command=self.browse_file
    )
    btn_browse.pack(side="left", padx=5)

    btn_analyze = ttk.Button(
        top_frame, text="تحليل الملف", command=self.analyze_file
    )
    btn_analyze.pack(side="left")

    # --- الجزء الأوسط: Notebook (تبويبات) ---
    self.notebook = ttk.Notebook(root)
    self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

    # تبويب 1: ملخص التوقعات والبيانات
    self.tab_summary = ttk.Frame(self.notebook, padding=10)
    self.notebook.add(self.tab_summary, text="الملخص والتوقعات")

    self.txt_summary = tk.Text(
        self.tab_summary,
        wrap="word",
        font=("Consolas", 10),
        bg="#f8f9fa",
        fg="#212529",
    )
    scroll_summary = ttk.Scrollbar(
        self.tab_summary, command=self.txt_summary.yview
    )
    self.txt_summary.configure(yscrollcommand=scroll_summary.set)
    scroll_summary.pack(side="right", fill="y")
    self.txt_summary.pack(fill="both", expand=True)

    # تبويب 2: جدول المتغيرات الجوية
    self.tab_vars = ttk.Frame(self.notebook, padding=10)
    self.notebook.add(self.tab_vars, text="عناصر الطقس المتاحة")

    cols = ("code", "name", "units")
    self.tree_vars = ttk.Treeview(
        self.tab_vars, columns=cols, show="headings", height=15
    )
    self.tree_vars.heading("code", text="الرمز")
    self.tree_vars.heading("name", text="الوصف / العنصر الجوي")
    self.tree_vars.heading("units", text="وحدة القياس")

    self.tree_vars.column("code", width=100, anchor="center")
    self.tree_vars.column("name", width=450, anchor="w")
    self.tree_vars.column("units", width=150, anchor="center")

    scroll_vars = ttk.Scrollbar(
        self.tab_vars, command=self.tree_vars.yview
    )
    self.tree_vars.configure(yscrollcommand=scroll_vars.set)
    scroll_vars.pack(side="right", fill="y")
    self.tree_vars.pack(fill="both", expand=True)

    # شريط الحالة السفلي
    self.status_var = tk.StringVar()
    self.status_var.set("جاهز لاستكشاف الملفات...")
    status_bar = ttk.Label(
        root,
        textvariable=self.status_var,
        relief="sunken",
        anchor="w",
        padding=5,
    )
    status_bar.pack(side="bottom", fill="x")

  def browse_file(self):
    """فتح نافذة مستكشف ملفات النظام لاختيار ملف GRIB"""
    filename = filedialog.askopenfilename(
        title="اختر ملف GRIB",
        filetypes=[
            ("ملفات GRIB", "*.grib *.grib2 *.grb *.grb2"),
            ("جميع الملفات", "*.*"),
        ],
    )
    if filename:
      self.file_path_var.set(filename)
      self.analyze_file()

  def analyze_file(self):
    """قراءة الملف واستخراج البيانات منه"""
    filepath = self.file_path_var.get().strip()

    if not filepath or not os.path.exists(filepath):
      messagebox.showerror(
          "خطأ", "يرجى اختيار ملف GRIB صحيح وموجود على الجهاز."
      )
      return

    self.status_var.set("جارٍ تحليل الملف، يرجى الانتظار...")
    self.root.update_idletasks()

    # مسح البيانات السابقة
    self.txt_summary.delete("1.0", tk.END)
    for item in self.tree_vars.get_children():
      self.tree_vars.delete(item)

    try:
      # قراءة الملف باستخدام xarray و cfgrib
      ds = xr.open_dataset(filepath, engine="cfgrib")

      # --- 1. بناء الملخص النصي ---
      summary_text = f"مسار الملف: {filepath}\n"
      summary_text += "=" * 60 + "\n\n"

      summary_text += "📅 [معلومات الزمن والتوقعات]:\n"
      if "time" in ds.coords:
        summary_text += f" • وقت الإصدار الأساسي (Base Time): {ds.time.values}\n"

      if "step" in ds.coords:
        steps = ds.step.values
        summary_text += f" • عدد خطوات التنبؤ: {len(steps) if hasattr(steps, '__len__') else 1}\n"
        summary_text += f" • مدى التوقعات (Forecast Steps): {steps}\n"

      if "valid_time" in ds.coords:
        summary_text += f" • أوقات صلاحية التوقعات (Valid Times):\n   {ds.valid_time.values}\n"

      summary_text += "\n🌍 [النطاق الجغرافي المغطى]:\n"
      if "latitude" in ds.coords and "longitude" in ds.coords:
        lats = ds.latitude.values
        lons = ds.longitude.values
        summary_text += (
            f" • خطوط العرض: من {lats.min():.2f}° إلى {lats.max():.2f}°\n"
        )
        summary_text += (
            f" • خطوط الطول: من {lons.min():.2f}° إلى {lons.max():.2f}°\n"
        )

      summary_text += "\n📊 [الأبعاد والمستويات الضغطية/الارتفاعات]:\n"
      for dim_name, dim_size in ds.dims.items():
        summary_text += f" • {dim_name}: {dim_size}\n"

      self.txt_summary.insert(tk.END, summary_text)

      # --- 2. تعبئة جدول المتغيرات ---
      for var_name in ds.data_vars:
        var = ds[var_name]
        long_name = var.attrs.get("long_name", var.attrs.get("name", "غير محدد"))
        units = var.attrs.get("units", "-")
        self.tree_vars.insert("", "end", values=(var_name, long_name, units))

      ds.close()
      self.status_var.set("تم تمحيل واستكشاف الملف بنجاح.")

    except Exception as e:
      self.status_var.set("حدث خطأ أثناء فتح الملف.")
      messagebox.showerror(
          "خطأ في القراءة",
          f"تعذر قراءة الملف عبر cfgrib.\n\nالتفاصيل:\n{str(e)}",
      )


if __name__ == "__main__":
  root = tk.Tk()
  app = GribExplorerApp(root)
  root.mainloop()