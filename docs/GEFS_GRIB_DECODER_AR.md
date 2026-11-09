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
## اختبار بيانات NOAA الحقيقية

أضيف سير عمل يدوي باسم **NOAA GEFS real GRIB2 ensemble smoke test** في GitHub Actions. من تبويب Actions شغّل هذا الاختبار يدوياً وحدد تاريخ التشغيل ودورة UTC وساعة التنبؤ والمتغير؛ يختار الاختبار مستوى 2 متر تلقائياً للحرارة و10 أمتار لمركبتي الرياح. ينزّل عضوين فعليين (`c00` و`p01`) من NOMADS، ثم يفك الحقل عبر cfgrib/ecCodes، ويتحقق من metadata والإحداثيات والوحدات، ويحسب المتوسط والانحراف المعياري ويحفظ ملفات GRIB2 وNPZ وملخص JSON كـ artifact.

الاختبار لا يعمل تلقائياً مع كل push، ولا يضمن توفر كل تشغيل قديم على NOMADS. الخرائط المعتمدة في هذا الاختبار محدودة عمداً إلى `TMP/2_m_above_ground` و`UGRD/10_m_above_ground` و`VGRD/10_m_above_ground`؛ أي توليفة أخرى تُرفض بدلاً من تخمين مفاتيح ecCodes. نجاحه يثبت فك البيانات الحقيقية لذلك التشغيل والحقل فقط، ولا يعد تحققاً علمياً شاملاً للتنبؤات.
