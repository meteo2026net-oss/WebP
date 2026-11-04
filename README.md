# WebP Weather Data Encoder

محرك أولي لتحويل مركبتي الرياح U/V من ملفات GRIB أو GRIB2 إلى نسيج RGB بصيغة WebP lossless، مع ملف JSON جانبي يوضح طريقة فك الترميز ومعلومات الشبكة.

## الملفات
- `wind_grib_to_webp.py`: محول حقول الرياح إلى WebP.
- `webp_to_npz.py`: فك ترميز WebP إلى مصفوفتَي U/V وقناع الصلاحية بصيغة NPZ.
- `inspect_grib.py`: فهرسة رسائل GRIB وحقولها ومستوياتها وأوقاتها ومعلومات الشبكة باستخدام ecCodes.
- `tests/`: اختبارات آلية لفك الترميز والتحقق من الأبعاد والقيم المفقودة.
- `.github/workflows/tests.yml`: تشغيل الاختبارات تلقائياً عند الدفع أو فتح Pull Request.
- `requirements.txt`: مكتبات Python المطلوبة.
- `docs/ENCODING.md`: مواصفات القنوات وفك الترميز.
- `docs/DATA_ACCESS.md`: ملاحظات الوصول إلى مجموعة WMO Support وتسلسل إدخال البيانات وحماية بيانات الدخول.
- `.gitignore`: استثناء الملفات المؤقتة والبيانات الكبيرة.

## المتطلبات والتثبيت
يتطلب Python 3.10 أو أحدث، ومكتبات ecCodes وcfgrib:

```bash
python -m pip install -r requirements.txt
```

قد يحتاج ecCodes إلى إعداد إضافي حسب نظام التشغيل. إذا تعذر فتح GRIB، راجع توثيق cfgrib وecCodes.

## التشغيل

```bash
python wind_grib_to_webp.py path/to/input.grib2 --output output/wind.webp
```

عند الحاجة إلى تحديد أسماء المتغيرات يدوياً:

```bash
python wind_grib_to_webp.py input.grib2 --u-var u10 --v-var v10 --output output/wind.webp
```

ينتج ملفا `wind.webp` و`wind.json`.

## فحص ملف GRIB قبل المعالجة

```bash
python inspect_grib.py path/to/input.grib2 --output output/grib_inventory.json
```

يعرض السكربت ملخصاً لكل رسالة GRIB (اسم الحقل، الوحدة، المستوى، خطوة التنبؤ، وقت الصلاحية، نوع الشبكة وأبعادها). هذه خطوة مهمة لأن أسماء الحقول الفعلية في تسليمات WMO قد تختلف عن الأسماء الافتراضية في محول الرياح.

## فك الترميز

```bash
python webp_to_npz.py output/wind.webp --output output/wind_decoded.npz
```

يقرأ السكربت ملف JSON المجاور، ويتحقق من إصدار الترميز وأبعاد الصورة وقناع الصلاحية، ثم يحفظ `u` و`v` و`valid` داخل ملف NPZ مضغوط. القيم المستعادة تبقى مقيدة بدقة الترميز 8-bit.

## الاختبارات

```bash
python -m pip install numpy Pillow
python -m unittest discover -s tests -v
```

يعمل GitHub Actions على تشغيل هذه الاختبارات تلقائياً.

## حدود النسخة الحالية
- لم يتم اختبارها بعد على ملف حقيقي من WMO Support dataset؛ قد تحتاج أسماء الحقول أو طريقة قراءة رسائل GRIB إلى ضبط.
- تدعم حالياً إحداثيات latitude/longitude أحادية البعد فقط.
- ترميز 8-bit يسبب quantization. وضع WebP lossless يحفظ قيم القنوات بعد الترميز دون فقد إضافي، لكنه لا يعيد دقة float الأصلية.
- احتفظ بملفات GRIB الأصلية للحسابات العلمية، وتحقق من إسقاط الشبكة واتفاقية خطوط الطول قبل عرض الصورة على الخريطة.
- لا ترفع ملفات GRIB الخاصة أو بيانات الدخول أو كلمات المرور إلى GitHub.

## المرحلة التالية
اختبار ملف ECMWF حقيقي، إضافة متغيرات الطقس الأخرى، توليد tiles، ثم بناء طبقة WebGL/MapLibre وتحريك التوقعات زمنياً.
