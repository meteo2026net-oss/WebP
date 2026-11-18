# تكامل ECMWF Open Data في WebP

هذا الموصل منفصل عن اتصال ECMWF WMO Support FTP الموجود في WebP. وهو يجلب مجموعة محددة من ملفات التنبؤات المفتوحة عبر مكتبة `ecmwf-opendata`، ثم يتحقق من سلامة GRIB قبل نشر الملف النهائي.

## التثبيت

يضيف المشروع `ecmwf-opendata` إلى متطلبات Python. بعد تحديث البيئة:

```powershell
python -m pip install -r requirements.txt
```

## مثال تنزيل انتقائي

```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.sources.ecmwf_open_data --model ifs --resolution 0p25 --time 0 --step 6 --param 2t 10u 10v --output downloads/ecmwf/ifs.grib2
```

يمكن تحديد تاريخ تشغيل باستخدام `--date YYYY-MM-DD`. يجب مراجعة توفر الدورة والمتغيرات وخطوات التنبؤ في كتالوج ECMWF قبل طلب التنزيل.

## المخرجات وسلامة البيانات

- ينشأ الملف أولاً بامتداد `.part`.
- لا يُنشر الملف النهائي إلا بعد اجتياز فحص GRIB.
- ينشأ ملف `.source.json` بجوار الملف، يتضمن النموذج والطلب والحجم وSHA-256 ووقت الاسترجاع.
- يمكن تمرير `catalog_sink` لربط الملف بكتالوج الأصول عند دمج الموصل مع طبقة الكتالوج.

## التحويل إلى الخرائط

بعد التنزيل، استخدم محول GRIB الموجود في WebP:

```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.grib_to_map downloads/ecmwf/ifs.grib2 --output-dir output/map_data/ecmwf
```

التحويل يدعم الحقول والشبكات التي يدعمها المحول الحالي فقط؛ اجتياز فحص GRIB لا يعني تلقائياً أن كل شبكة أو حقل قابل للرسم.

## الترخيص

يجب إظهار الإسناد المطلوب لبيانات ECMWF والالتزام بترخيص وشروط كل مصدر بيانات. لا تُضمّن بيانات التنزيل في Git.
