# تقرير التحقق من GRIB2 الحقيقي وOutbox

تاريخ التقرير: 2026-11-09  
المستودع: `meteo2026net-oss/WebP`  
الفرع: `feat/windows-one-click-desktop-package`  
الرأس المفحوص: `6cec686981511da42db2f3c7351b5cd6045bd944`  
PR: #71 (مفتوح / Draft؛ لم يتم الدمج).

## نتائج CI على الرأس نفسه

| المسار | التشغيل | النتيجة |
|---|---:|---|
| Python tests | [42538067815](https://github.com/meteo2026net-oss/WebP/actions/runs/42538067815) | success |
| Windows desktop package | [42538067808](https://github.com/meteo2026net-oss/WebP/actions/runs/42538067808) | success |
| ECMWF real GRIB2 | [42538062291](https://github.com/meteo2026net-oss/WebP/actions/runs/42538062291) | success |
| NOAA GEFS real GRIB2 | [42538062348](https://github.com/meteo2026net-oss/WebP/actions/runs/42538062348) | failure |

## ECMWF

- المصدر: عينة GRIB2 ثابتة من مستودع بيانات ECMWF.
- الملف: `sample.grib2`.
- الحجم: 11,567,838 bytes.
- ecCodes فكّ 145 رسالة GRIB2.
- المتغير: `msl` (Mean sea level pressure)، الوحدة Pa.
- تم إنتاج مخرجات PNG وNPZ والتحقق من 145 طبقة، والإحداثيات، ووجود 65,160 خلية صالحة في كل طبقة.
- SHA-256 للملف المصدر:

```
3db07acddc46e71de0ec51214ddefdd478b0e520dbdfe191ae33da92de5309fd
```

- Artifact ID: `13639184796`.
- حجم Artifact: 66,075,935 bytes.
- SHA-256 لأرشيف Artifact:

```
6be28390414ddbd50d2dccecb6fab48d34feb0c59628a19565e3b3b3b624fd51
```

[فتح تشغيل ECMWF وملفاته](https://github.com/meteo2026net-oss/WebP/actions/runs/42538062291).

## NOAA GEFS

- المصدر المطلوب: NOAA/NCEP NOMADS، منتج GEFS 0.5 degree.
- التشغيل استخدم التاريخ 2026-11-08، الدورة 00 UTC، والتنبؤ +24 ساعة.
- العضوان: c00 وp01.
- استجابة كل طلب كانت ملف GRIB2 بطول 182 bytes، مع إطار GRIB2 شكلياً، لكنها لا تحتوي الحقل المطلوب `2t / heightAboveGround / 2.0`. لذلك فشل فكّ البيانات وحساب إحصاءات التجميع. لا تُعدّ هذه ملفات GEFS صالحة للاستخدام التحليلي.

| العضو | الحجم | SHA-256 |
|---|---:|---|
| c00 | 182 bytes | `00e496f0045d6dfab16c1bfe9871c051cbb2726f6dfe7dddf9e512893f50fe34` |
| p01 | 182 bytes | `e7e552ab9b9cd9e8bbf2dc6d897fc71b084e5bf8bad3498ba1d4354570dc0de4` |

- Artifact ID: `13640450705`.
- حجم Artifact: 2,483 bytes.
- SHA-256 لأرشيف Artifact:

```
3d5d4147a4df3cd3ba1aad79d28a4ecb68ecbc49b65e293d0fdcab89dcf9f99a
```

[فتح تشغيل NOAA وملفاته](https://github.com/meteo2026net-oss/WebP/actions/runs/42538062348).

## Outbox والتزامن

- Python CI نجح على الرأس أعلاه، ويشمل اختبار العاملين المستقلين.
- اختبار استعادة ما بعد التزام الوجهة يحقن فشل اتصال مضبوط عند حدّ تأكيد المصدر، ثم يتحقق من إعادة المحاولة دون تكرار الأصل.
- هذا الاختبار ليس فصلاً فعلياً لاتصال TCP بين خادمين مستقلين. اختبار TCP/قاعدة بيانات شبكية مستقلة ما زال غير منفذ، ولا ينبغي وصفه بأنه اجتاز.

## القيود والاستنتاج

1. ECMWF real-data smoke test اجتاز على هذا الرأس مع ملف GRIB2 حقيقي ومخرجات قابلة للتنزيل.
2. NOAA لم يجتز؛ سلامة إطار GRIB2 وحدها غير كافية، ويجب أن يثبت الاختبار وجود المتغير/المستوى والبيانات الشبكية المتوقعة قبل قبول الملف.
3. لا توجد نتيجة تشغيل فعلية لمصدر WMO في هذه الجولة؛ النتائج أعلاه تخص ECMWF وNOAA فقط.
4. يلزم اختبار فصل TCP حقيقي، ثم إعادة تشغيل NOAA بعد تحديد سبب الاستجابة الصغيرة وإصلاحه.
5. لم يتم دمج PR #71 ولم يتم تعديل `main`.
