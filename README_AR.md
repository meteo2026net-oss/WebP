# ECMWF Data Collector — مشروع تنزيل ومعالجة البيانات الجوية

## هيكل المشروع
- `src/ecmwf_collector/`: منطق الاتصال والتنزيل والتحقق وحفظ الحالة.
- `src/ecmwf_collector/gui/`: الواجهة الرسومية العربية المبنية بـ PySide6.
- `src/ecmwf_collector/tools/`: أدوات فحص GRIB وتحويل الرياح إلى WebP وفك الترميز ومستكشف الملفات.
- `tests/`: الاختبارات وخادم FTP الوهمي.
- `docs/`: توثيق الوصول والترميز والبنية.
- `config/settings.example.json`: نموذج إعدادات آمن؛ انسخه إلى `config/settings.json` محلياً.
- `archive/`: نسخة الأرشيف الأصلي للرجوع إليها.

## التثبيت على Windows
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item config/settings.example.json config/settings.json
python main.py
```

أدخل بيانات الاتصال داخل التطبيق فقط. لا ترفع كلمة المرور أو ملف الإعدادات المحلي أو ملفات GRIB أو قاعدة البيانات إلى GitHub. يفضّل استخدام FTPS؛ الاتصال FTP العادي غير مشفر ومعطل افتراضياً.

## فحص ملفات GRIB
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.inspect_grib path/to/input.grib2 --output output/grib_inventory.json
```

## تحويل الرياح إلى WebP
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.wind_grib_to_webp path/to/input.grib2 --output output/wind.webp
python -m ecmwf_collector.tools.webp_to_npz output/wind.webp --output output/wind_decoded.npz
```

## الاختبارات
```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -t . -v
```

الاختبارات تستخدم بيانات اصطناعية وخادم FTP وهمياً، ولا تثبت نجاح الاتصال بالخادم الحقيقي.

## حدود محول الرياح الحالي
يستخدم ترميزاً كمياً بدقة 8-bit ويدعم حالياً إحداثيات latitude/longitude أحادية البعد. احتفظ بملفات GRIB الأصلية للحسابات العلمية، وتحقق من الإسقاط والاتجاه ونطاق خطوط الطول والإسناد الجغرافي قبل عرض الصور على الخريطة.
