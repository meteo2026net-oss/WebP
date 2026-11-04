# ECMWF Data Collector — نظام تنزيل ومعالجة وعرض البيانات الجوية

الهدف هو بناء مسار متكامل: **تنزيل GRIB من ECMWF ← فحص الحقول ← تحويلها إلى طبقات جغرافية ← عرضها على خريطة تفاعلية**.

## مكونات المشروع
- `src/ecmwf_collector/`: الاتصال بالخادم، استعراض الملفات، التنزيل والاستكمال والتحقق.
- `src/ecmwf_collector/gui/`: واجهة سطح المكتب العربية.
- `src/ecmwf_collector/tools/`: فحص GRIB والتحويل والمعالجة الجماعية.
- `map_viewer/`: واجهة الخريطة التفاعلية المبنية على Leaflet.
- `tests/`: اختبارات آلية وبيئة FTP وهمية.
- `docs/`: التوثيق الفني.
- `config/settings.example.json`: نموذج إعدادات آمن.
- `archive/`: الأرشيف الأصلي للمرحلة الثانية.

## التثبيت على Windows
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item config/settings.example.json config/settings.json
python main.py
```

أدخل بيانات ECMWF داخل التطبيق فقط. لا ترفع كلمة المرور أو ملف الإعدادات المحلي أو قاعدة البيانات أو ملفات GRIB المقيدة إلى GitHub. يفضّل FTPS/TLS؛ FTP العادي غير مشفر.

## سير العمل الكامل

### 1. تنزيل البيانات
شغّل `python main.py`، ثم أدخل بيانات اتصال WMO Support، اختبر الاتصال، استعرض المجلدات، وحدد المنتجات والفترة، ثم نزّل الملفات. يحفظ البرنامج الملفات الأصلية محلياً في مجلد التنزيل.

### 2. فحص ملف GRIB
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.inspect_grib path/to/file.grib2 --output output/inventory.json
```

### 3. تحويل الحقول إلى طبقات خريطة
```powershell
python -m ecmwf_collector.tools.grib_to_map path/to/file.grib2 --output-dir output/map_data
```
يحوّل الحقول العددية ثنائية الأبعاد المتوافقة مع شبكة خطوط طول وعرض منتظمة إلى PNG شفاف، وينشئ ملفات JSON جانبية وقائمة طبقات `manifest.json`.

### 4. معالجة جميع الملفات المنزلة
```powershell
python -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output/map_data
```

### 5. تحويل الرياح U/V
```powershell
python -m ecmwf_collector.tools.wind_grib_to_webp path/to/wind.grib2 --output output/wind.webp
```
ينتج WebP علمياً مشفراً، وPNG لسرعة الرياح، ويسجل طبقة العرض تلقائياً في manifest.

### 6. فتح الخريطة التفاعلية
من جذر المستودع:
```powershell
python serve_map.py
```
ثم افتح:
`http://127.0.0.1:8765/map_viewer/`

تستطيع اختيار الطبقة، تغيير شفافيتها، وتكبير نطاقها. يلزم تشغيل الخادم المحلي لأن المتصفح لا يقرأ manifest عبر `file://` مباشرة.

## الاختبارات
```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -t . -v
```

## الحدود الحالية
- محرك الخريطة الأولي يدعم شبكات latitude/longitude أحادية البعد والمنتظمة.
- شبكات rotated-pole وLambert وpolar stereographic والشبكات المنحنية تحتاج إعادة إسقاط قبل العرض.
- ليست كل ملفات GRIB قابلة للفتح في مجموعة واحدة؛ بعض الملفات تحوي مجموعات حقول مختلفة، وقد تتطلب تحديد المتغير أو فصل الرسائل.
- WebP الحالي يستخدم quantization بدقة 8-bit؛ احتفظ بملفات GRIB الأصلية للحسابات العلمية.
- لم يُختبر الاتصال الحقيقي بـ ECMWF أو عرض بيانات ECMWF فعلية بعد؛ يلزم إجراء اختبار تكاملي باستخدام ملف GRIB مسموح بتداوله.
