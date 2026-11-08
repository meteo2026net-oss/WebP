# كتالوج أصول الملفات — دليل التنفيذ الأول

## الغرض والنطاق

أضيفت الوحدة `ecmwf_collector.file_asset_catalog.FileAssetCatalog` لتسجيل **أصول الملفات الخام** مثل GRIB2 وNetCDF وCSV في قاعدة بيانات محددة. لا تستخرج هذه الوحدة حقول الطقس ولا تحوّلها إلى قياسات أو تنبؤات رقمية.

تدعم طبقة الاتصال الحالية SQLite وPostgreSQL وMySQL/MariaDB. إنشاء المخطط عملية صريحة عبر `initialize_schema()`؛ لا ينشئ المُنشئ اتصالاً ولا يكتب إلى قاعدة البيانات. لا يستدعي أي موصل تنزيل هذه العملية تلقائياً.

## الاستخدام البرمجي

```python
from ecmwf_collector.file_asset_catalog import FileAsset, FileAssetCatalog

catalog = FileAssetCatalog(selected_profile, secrets)
catalog.initialize_schema()  # خطوة إعداد صريحة بعد موافقة المستخدم

asset = FileAsset(
    provider_id="noaa_nomads",
    model_id="noaa_gfs",
    product_id="surface_0p25",
    local_path=r"C:\\Weather\\gfs.grib2",
    content_type="application/x-grib2",
    size_bytes=123456,
    sha256="<64-character-sha256>",
    run_time_utc="2026-11-08T00:00:00Z",
    valid_time_utc="2026-11-08T06:00:00Z",
    source_uri="https://nomads.ncep.noaa.gov/...",
    validation_status="framing_checked",
    metadata_json='{"variables":["TMP","UGRD"]}',
)
result = catalog.register_asset(asset)
```

## الجداول

- `webp_file_assets`: سجل موحد للملف، هوية المصدر/النموذج/المنتج، دورة التشغيل والصلاحية والعضو، الحجم والبصمة ونوع المحتوى والحالة والبيانات الإضافية.
- `webp_file_asset_sources`: مصادر URI المتعددة التي تشير إلى الأصل نفسه. يمنع قيد فريد تكرار URI نفسه، بينما يسمح بحفظ مصدرين مختلفين للمحتوى نفسه.

يُحسب مفتاح الأصل من المزود والنموذج والمنتج ودورة التشغيل ووقت الصلاحية والعضو وSHA-256. لذلك لا يدمج ملفات من نماذج أو منتجات أو دورات مختلفة لمجرد تشابه البصمة، كما لا يكرر الملف عند إعادة تسجيل الهوية نفسها.

## المعاملات والسلامة

- إدخال الأصل ومصدره يتمان في معاملة واحدة؛ فشل تسجيل المصدر يعيد المعاملة كلها.
- لا تُحذف ملفات GRIB/CSV المحلية ولا تعدّل.
- كلمات المرور لا تدخل في سجل الأصل ولا في JSON.
- الاتصال المعطّل أو كلمة المرور المفقودة يؤديان إلى فشل مغلق.
- `metadata_json` يجب أن يكون كائن JSON، وحالة التحقق محصورة في `unverified`, `framing_checked`, `validated`, `rejected`.
- لا يُفترض أن `framing_checked` يعني تحققاً علمياً من صحة التنبؤ.

## ما لم يُنفذ بعد

1. استدعاء الكتالوج من موصلات التنزيل بعد نجاح الفحص وحفظ sidecar.
2. تمرير معرفات provider/model/product موثوقة من طلب التنزيل إلى التسجيل.
3. واجهة اختيار قاعدة الوجهة ومعاينة مخطط الأصول ثم موافقة صريحة قبل إنشاء الجداول.
4. Outbox وإعادة المحاولة ونقل الأصول إلى مخزن مركزي.
5. مخطط مستقل للقيم الجوية المستخرجة من GRIB/NetCDF.

لا تُعتبر إضافة هذه الوحدة ربطاً حياً للتوجيه ولا استيراداً تلقائياً للبيانات. لا تُشغّل `initialize_schema()` على قاعدة المستخدم قبل مراجعة المخطط والموافقة الصريحة.
