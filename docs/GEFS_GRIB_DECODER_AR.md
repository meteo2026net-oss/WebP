# قارئ حقول GEFS GRIB2 والتحقق من قابلية المقارنة

يوفر `ecmwf_collector.gefs_decoder` طبقة فك حقول باستخدام `cfgrib` وecCodes. يجب على المستدعي تحديد مفاتيح ecCodes الدقيقة: `short_name` و`type_of_level` و`level`.

تقرأ الطبقة ملفات sidecar أولاً، ثم تفك الحقل المحدد من كل عضو، وتتحقق من وقت التهيئة ووقت الصلاحية وساعة التنبؤ، وشكل الشبكة وإحداثيات خطوط العرض والطول والوحدات. أي اختلاف يوقف التجميع برسالة واضحة.

مثال:

    from ecmwf_collector.gefs_decoder import decode_gefs_ensemble_fields
    fields, metadata = decode_gefs_ensemble_fields(
        ["gefs_c00.grib2", "gefs_p01.grib2"],
        short_name="t", type_of_level="heightAboveGround", level=2,
    )

بعد ذلك فقط يمكن تمرير `fields` إلى `calculate_ensemble_statistics`.

لا يحول هذا الإصدار الوحدات ولا يترجم أسماء متغيرات NOMADS تلقائياً إلى مفاتيح ecCodes؛ على المستدعي اختيار تعريف الحقل الصحيح. كما أن اختبارات المحاكاة لا تثبت نجاح فك ملف NOAA حي.