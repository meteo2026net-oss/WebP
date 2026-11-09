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


## متابعة 2026-11-09: اختبار TCP وتشخيص NOMADS

### اختبار TCP على MariaDB

نجح الاختبار الفعلي `test_mariadb_outbox_recovers_after_real_tcp_drop_before_source_ack` في Python CI على commit `846ad03c50a8a38030061b08f5c1a3de1066cc02`:
- تم قطع اتصال TCP واحد عبر وسيط محلي عند تأكيد المصدر بعد التزام الوجهة.
- فشل تأكيد المصدر كما هو متوقع، ثم نجحت إعادة المحاولة.
- بقي الأصل موجوداً في الوجهة بنسخة واحدة، واختفى الحدث من قائمة Outbox المعلّقة بعد الاستعادة.
- نتيجة CI: [Python run 42539808880](https://github.com/meteo2026net-oss/WebP/actions/runs/42539808880).
- سجل الاختبار يؤكد `...real_tcp_drop_before_source_ack ... ok`، كما نجحت اختبارات PostgreSQL وMySQL وMariaDB التكاملية في التشغيل نفسه.

وبذلك اجتاز اختبار قطع TCP بين تطبيق المصدر وخدمة MariaDB عبر TCP proxy في بيئة CI. لا يعني ذلك اختبار انقطاع شبكة بين موقعين جغرافيين أو شبكتين مستقلتين.

### تشخيص NOAA NOMADS

فحصت أرشيف Artifact الفاشل `13640492716` مباشرة. الاستجابتان كانتا GRIB2 مؤطرتين بطول 182 بايت، لكنهما لا تمثلان حقول شبكة صالحة للتحليل، ولا تحتويان الحقل المطلوب. البصمات في قسم NOAA أعلاه تخص هاتين الاستجابتين غير الصالحتين.

بمقارنة بناء الطلب مع إرشادات NOMADS الرسمية، ظهر أن الطلب يرسل `subregion=` فارغاً من دون إحداثيات نطاق. أزيل هذا المحدد الفارغ من `build_gefs_url` لطلب الشبكة الكاملة، وأضيف اختبار وحدة يثبت عدم إرساله:
- [تعديل مصدر NOAA](https://github.com/meteo2026net-oss/WebP/commit/f5fd810c012f6815c0ed8932001db0ffd9fb0b09)
- [اختبار URL](https://github.com/meteo2026net-oss/WebP/commit/c0056c2c4981222916037e1fcae584df04bac81b)
- مرجع NOMADS: https://nomads.ncep.noaa.gov/gribfilter.php?ds=gefs_atmos_0p50a
- مثال توثيقي لطلبات GEFS يوضح استخدام محددات النطاق عند تفعيل خيار subregion: https://publicwiki.deltares.nl/spaces/FEWSDOC/pages/370606523/NomadsGribFilterServer

**الحالة:** إصلاح الطلب موجود في الفرع، لكن لم تُثبت صحته ببيانات NOAA جديدة بعد. تشغيلات ECMWF وNOAA وPython وWindows على الرأس `c0056c2c4981222916037e1fcae584df04bac81b` ما زالت قيد التنفيذ عند تحديث هذا التقرير.

### WMO

لم أجد ضمن ملفات المشروع Workflow أو اختبار تنزيل GRIB2 فعلياً من مصدر WMO مستقل؛ الموجود حالياً اختبارا ECMWF وNOAA فقط. لذلك لا أدرج نتيجة WMO ناجحة أو بصمة منسوبة إليه.


## تحديث حاسم على الرأس 1c4a18ba2eec5d48c0fb7ce00503e2e3848df2c0 — 2026-11-09

هذا القسم أحدث من حالات NOAA/ECMWF السابقة أعلاه، ويصححها بالنسبة إلى الرأس الحالي فقط.

### NOAA GEFS — اجتاز اختبار البيانات الحقيقية

- Workflow: [42540998783](https://github.com/meteo2026net-oss/WebP/actions/runs/42540998783) — **success** على الرأس الحالي.
- المصدر: NOAA/NCEP NOMADS، GEFS بدقة 0.50 درجة.
- دورة التشغيل: 2026-11-08 00 UTC؛ التنبؤ +24 ساعة؛ وقت الصلاحية 2026-11-09 00:00 UTC.
- الحقل: `TMAX` / ecCodes `tmax`، Maximum temperature، الوحدة K.
- inventory الفعلي للعضوين c00 وp01: `paramId=3015`، `typeOfLevel=heightAboveGround`، `level=2`، `stepType=max`، `stepRange=18-24`، والشبكة `regular_ll`.
- تم فك الحقل فعلياً من الملفين، وحساب mean وspread وmember_count على شبكة `361 × 720`.
- عدد الخلايا الصالحة: 259,920 للمتوسط و259,920 للانتشار. قيمة `member_count` تساوي 2 في جميع الخلايا الـ259,920.
- تحقق فحص الأرشيف محلياً: ZIP سليم بلا أخطاء CRC؛ كلا الملفين يبدأ بترويسة GRIB وإصدار 2 وينتهي بـ`7777`.
- أحجام وبصمات SHA-256 للملفات:
  - c00: 232,945 bytes — `704e8023de4636bb3bb754e9c3069b0f0f8106fca9185ae0d98a446d8e1d4c0f`
  - p01: 234,031 bytes — `f99a5aebfb6c1fa9ba65676d1a8ad54180f8342fbec4279243c22880f6e5c9b7`
- Artifact ID: `13640899062`؛ الحجم 1,554,461 bytes؛ SHA-256 للأرشيف `f1a275f0fd58c4ebbea2f76d6339f6dc13c88ebcb93c7ad97ebfb82831dba401`.
- أُصلح مسار فك المستوى في decoder ليقرأ قيمة coordinate `heightAboveGround` عند غياب `GRIB_level` من attrs، وأضيف اختبار وحدة لهذا السلوك.
- هذا smoke test يثبت تنزيل الحقل وفكّه وحساب إحصاءات العضوين المختارين؛ لا يمثل تحققاً علمياً من دقة التنبؤ ولا إحصاءات كامل أعضاء GEFS.

### ECMWF — اجتاز على الرأس نفسه

- Workflow: [42540998832](https://github.com/meteo2026net-oss/WebP/actions/runs/42540998832) — **success** على الرأس الحالي.
- ecCodes فك 145 طبقة حقيقية للمتغير `msl` بوحدة Pa.
- تم التحقق من قيم المصدر والإحداثيات ومخرجات PNG وNPZ؛ 65,160 خلية صالحة في كل طبقة.
- Artifact ID: `13641710883`؛ الحجم 66,075,935 bytes؛ SHA-256 للأرشيف `8a7cd9b9f2906d3e05e6c92dbdaabac830e05b01779d925e111246a95b8ad9b2`.

### اختبارات Python على الرأس نفسه

- Workflow: [42541001600](https://github.com/meteo2026net-oss/WebP/actions/runs/42541001600) — **success**.
- اجتاز 529 اختباراً في 19.415 ثانية، مع نجاح compilation وفحص JavaScript.
- لا تعني هذه النتيجة أن اختبار Windows package أو قبول المستخدم على جهاز نظيف قد اكتمل.

### حالة Windows وWMO والقبول

- Windows desktop package على الرأس نفسه: [42541001604](https://github.com/meteo2026net-oss/WebP/actions/runs/42541001604) كان قيد التنفيذ عند آخر فحص؛ اجتازت compilation و529 اختباراً، وكان بناء مجلد PyInstaller جارياً. لا توجد بعد نتيجة نهائية أو Artifact ويندوز لهذا الرأس.
- لا يوجد اختبار مصدر WMO مستقل في هذه النتائج؛ لا ننسب ملفات ECMWF أو NOAA إلى WMO.
- PR #71 ما زال مفتوحاً وDraft وغير مدمج. لم يُعدّل `main`.
- تبقى تجربة قبول على جهاز Windows نظيف، واختبار PostgreSQL فعلي اختياري على قاعدة بيانات تجريبية، خارج ما تثبته CI.


## متابعة الرأس a98db397fc9034f40b71871f7c0de0408257e989 — 2026-11-09

### إعادة التحقق من المصادر وPython

- NOAA GEFS: [Workflow 42541365650](https://github.com/meteo2026net-oss/WebP/actions/runs/42541365650) — **success** على هذا الرأس. تم فحص Artifact ID `13641582025`؛ أرشيف ZIP سليم، وبصمات ملفات GRIB2 تطابق `SHA256SUMS.txt`، وملفات الإحصاءات تتضمن mean وspread وmember_count. العضوان c00 وp01، وmember_count=2 في 259,920 خلية.
- SHA-256 لأرشيف NOAA: `294f581629536c213419a20964bf09635ca3001f2dfb6def9effa357c7dbba0a`.
- ECMWF: [Workflow 42541365624](https://github.com/meteo2026net-oss/WebP/actions/runs/42541365624) — **success** على هذا الرأس؛ تم فك 145 طبقة msl والتحقق من قيم المصدر والإحداثيات وPNG وNPZ.
- SHA-256 لأرشيف ECMWF: `9eba00648ad14ad2e55e4250bf063db47907fc78c0c43e133a343994c00fd037`.
- Python: [Workflow 42541369721](https://github.com/meteo2026net-oss/WebP/actions/runs/42541369721) — **success**؛ 529 اختباراً، `Ran 529 tests in 17.215s`.

### Windows portable package

- [Workflow 42541369741](https://github.com/meteo2026net-oss/WebP/actions/runs/42541369741) على الرأس أعلاه. المحاولة الأولى أُلغيت قبل تنفيذ خطوات البناء، وأعيد تشغيل الـjob منفرداً (attempt 2).
- عند تحديث هذا القسم كانت المحاولة الثانية في حالة `in_progress` عند خطوة تثبيت التطبيق وPyInstaller؛ لم تصل بعد إلى ترجمة المصادر أو الاختبارات أو PyInstaller أو preflight أو رفع Artifact.
- لا يوجد Artifact Windows مثبت لهذه المحاولة، لذلك لا نعلن اكتمال الحزمة.
- [قائمة القبول الميداني](WINDOWS_FINAL_ACCEPTANCE_AR.md) ما زالت تتطلب تجربة على جهاز Windows مستقل بعد توفر الحزمة.

### WMO WIS2 — خطة تحقق مصدر مستقل، لا نتيجة نجاح

- يوضح [دليل WMO WIS2 الرسمي](https://wmo-im.github.io/wis2-guide/guide/wis2-guide-APPROVED.html) أن اكتشاف مجموعات البيانات يتم عبر Global Discovery Catalogue، وأن سجلات WCMP2 تحتوي روابط قابلة للتنفيذ لتنزيل البيانات أو الوصول إلى API/الاشتراك.
- يوضح [دليل WMO للعثور على البيانات وتنزيلها وفكها](https://etrp.wmo.int/pluginfile.php/98056/mod_page/content/14/finding-downloading-and-decoding-data.pdf) واجهات GDC الخاصة بـ DWD وCMA وECCC وآلية الوصول إلى البيانات.
- خطة الاختبار المقترحة: اكتشاف سجل dataset من GDC، حفظ سجل metadata وروابطه وسياسة البيانات، اختيار رابط تنزيل canonical أو رابط data granule موثق، تنزيل ملف GRIB2 من عقدة WIS2، ثم التحقق باستخدام ecCodes من GRIB edition والرسائل والحقول والمستويات والأوقات والشبكة، وحساب SHA-256 قبل فك الحقل وحساب الإحصاءات.
- لا يوجد حتى الآن سجل dataset محدد تم جلبه وفحصه، ولا ملف GRIB2 مستقل تم تنزيله عبر WIS2 في هذا التشغيل. لذلك تظل WMO **غير مختبرة عملياً**؛ ولا تُنسب نتائج NOAA أو ECMWF إلى WMO.

### حالة المراجعة

- PR #71 مفتوح وDraft وغير مدمج.
- الرأس الحالي عند كتابة هذا القسم: `a98db397fc9034f40b71871f7c0de0408257e989`.
- لم يتم تعديل `main`.


## نتيجة الحزمة المحمولة على الرأس f44c3805287b9f03c67b1587172b5681587f4959 — 2026-11-09

### Windows x64 — نجاح البناء وفحص Artifact مستقلاً

- Workflow: [42541662604](https://github.com/meteo2026net-oss/WebP/actions/runs/42541662604) — **success** على الرأس `f44c3805287b9f03c67b1587172b5681587f4959`.
- اكتملت كل الخطوات: تثبيت الاعتماديات، compile، اختبارات الوحدة، PyInstaller، التحقق من EXE، إضافة `START.bat` وأداة القبول، إنشاء manifest، تشغيل packaged preflight، التحقق من تغطية SHA-256، ورفع Artifact.
- Artifact: `ECMWFWebP-Windows-x64`، ID `13641533485`، الحجم `157,085,002` bytes، انتهاء الصلاحية `2026-11-23`.
- SHA-256 لأرشيف ZIP: `f7188c8bc9e5286ce28e690fc496798f5a8b757169997ebe16c3a1c1cdcec4c0`.
- تم تنزيل الأرشيف وفحصه مستقلاً: ZIP CRC سليم؛ 3,979 ملفاً؛ manifest يحتوي 3,979 إدخالاً؛ لا ملفات مفقودة أو زائدة أو مكررة؛ كل بصمات SHA-256 تطابقت.
- `ECMWFWebP.exe` موجود وحجمه 24,279,938 bytes، ترويسة PE سليمة ومعمارية AMD64/x64.
- أداة القبول المضمنة وُجدت مع `START.bat` و`SHA256SUMS.txt`. فحص Windows runner اجتاز تشغيل التطبيق وخادم الخرائط المحلي وملفات HTML/CSS/JS.
- [تنزيل Artifact من GitHub Actions](https://github.com/meteo2026net-oss/WebP/actions/runs/42541662604/artifacts/13641533485).

**حدود القبول:** هذا يثبت البناء والفحص الآلي على Windows runner، ولا يثبت بعد تجربة المستخدم على جهاز Windows مستقل أو اتصال ECMWF بمفاتيح المستخدم أو إعداد PostgreSQL الحقيقي. راجع [قائمة القبول الميداني](WINDOWS_FINAL_ACCEPTANCE_AR.md).

### NOAA GEFS وECMWF وPython على الرأس نفسه

- Python: [42541662543](https://github.com/meteo2026net-oss/WebP/actions/runs/42541662543) — **success**؛ 529 اختباراً في 17.494 ثانية.
- NOAA GEFS: [42541656536](https://github.com/meteo2026net-oss/WebP/actions/runs/42541656536) — **success**؛ Artifact ID `13641636511`، الحجم 1,554,460 bytes، SHA-256 للأرشيف `0b562fedd47f787264ae162709a11899b27889291bd568d57f065f54c4cc0dfa`.
- فحص NOAA المستقل: ZIP سليم، وبصمات ملفات GRIB2 تطابق manifest. تم فك العضوين c00 وp01 للحقل TMAX عند 2m، وحُسب mean/spread على شبكة 361×720؛ جميع 259,920 خلية لها member_count=2. يظل هذا smoke test لعضوين فقط، وليس تحققاً علمياً للتنبؤ أو كامل أعضاء GEFS.
- ECMWF: [42541656498](https://github.com/meteo2026net-oss/WebP/actions/runs/42541656498) — **success**؛ تحقق سجل التشغيل من 145 طبقة msl حقيقية وقيم المصدر والإحداثيات ومخرجات PNG وNPZ. Artifact ID `13641332379`، الحجم 66,075,935 bytes، SHA-256 للأرشيف `c95cff0d0f1a9386a316e00c3bf45f0665e46a18046579dddd742299efcb30fe`.

### WMO WIS2 — نتيجة استكشاف الكتالوج

- تم الوصول إلى [WIS2 Global Discovery Catalogue](https://wis2-gdc.weather.gc.ca/collections/wis2-discovery-metadata?f=json) واستعراض سجلات WCMP2؛ يؤكد الكتالوج وجود سجلات مجموعات بيانات وروابط خدمات واكتشاف، لكنه لا يعني أن كل سجل يوفّر ملف GRIB2.
- يوضح [دليل WMO الرسمي](https://wmo-im.github.io/wis2-guide/guide/wis2-guide-APPROVED.html) أن GDC يصف روابط التنزيل وواجهات API والاشتراك، وأن روابط البيانات الفعلية قد تكون على عقدة الناشر أو Global Cache.
- لم يُعثر في هذه الجولة على سجل GRIB2 محدد مع رابط binary مباشر صالح تم تنزيله وفكّه بواسطة ecCodes. لذلك تبقى WMO **غير مجتازة لاختبار GRIB2 مستقل**، ولا ننسب إليها نتائج NOAA أو ECMWF.

### حالة PR

- PR #71 ما زال مفتوحاً وDraft وغير مدمج.
- لم يتم تعديل `main`.


## اختبار WMO WIS2 مستقل — DWD ICON-EPS — 2026-11-09

### نتيجة فك GRIB2 الفعلي

- أُضيف Workflow مستقل: `.github/workflows/wmo-wis2-grib2-smoke.yml`.
- اكتُشف سجل WCMP2 عبر WIS2 GDC:
  `urn:wmo:md:de-dwd:icon-eps.ALL` — **Global Ensemble Prediction Model**، المنتج ICON-EPS من Deutscher Wetterdienst (DWD).
- سجل GDC يعلن التنسيق GRIB2 وسياسة `core` وإتاحة مجانية غير مقيدة، ويشير إلى خادم Open Data الخاص بـDWD.
- Workflow: [42543067275](https://github.com/meteo2026net-oss/WebP/actions/runs/42543067275) — **success**.
- اختير ملف دورة 2026-11-08 12 UTC والتنبؤ +6 ساعات: `fc_2026110812icgle_006.grib`، الحجم الكلي المعلن 199,950,268 bytes.
- استُخدم HTTP Range لجلب مقدمة الملف، ثم استُخرجت أول رسالة GRIB2 كاملة بطول 1,333,869 bytes، وتحقق ecCodes من الإصدار 2 وفكّ القيم.
- الحقل المفكوك: `max_i10fg`، Time-maximum 10 metre wind gust، الوحدة `m s**-1`، المستوى 10m، `gridType=regular_ll`، مركز `edzw`.
- الشبكة: 1440 × 721 = 1,038,240 نقطة؛ جميع 1,038,240 قيمة صالحة. المجال العددي المرصود في الرسالة: 0.850178 إلى 40.719319 m/s.
- SHA-256 للرسالة المستخرجة: `85d06b7ce18e2e4bd9f6db62621f6e6cdabf17f8834dd101cdbad800294a886c`.
- أعيد التشغيل بعد إصلاح تنسيق ملفات الإثبات: [Workflow 42543144898](https://github.com/meteo2026net-oss/WebP/actions/runs/42543144898) — **success** على الرأس `656eeae0e6aa558ade72fa8283621f2861fe83b8`.
- Artifact النهائي: ID `13641334424`، الحجم 1,334,319 bytes، SHA-256 للأرشيف `db704aa062d64b3f9bb27f8433dc469deaa3d57e6bbc1095c2fbe067bb97916c`.
- فحص الأرشيف مستقلاً: ZIP CRC سليم؛ JSON metadata/inventory/summary قابلة للقراءة؛ manifest فيه إدخال واحد وتطابق SHA-256 لرسالة GRIB2 المستخرجة.
- استجابة Range كانت HTTP 206، وجلبت 32 MiB من ملف حجمه 199,950,268 bytes؛ الرسالة الأولى كاملة بطول 1,333,869 bytes.
- هذه نتيجة اختبار فك رسالة حقيقية واحدة من مجموعة ICON-EPS عبر سجل WIS2؛ لا تمثل فك كامل ملف 199 MB ولا تحققاً علمياً للتنبؤ.

### فحص سجل قبرص وسبب استبعاده

- جرى اختبار سجل WIS2 الآخر `urn:wmo:md:cy-dom:weather.prediction.deterministic.local` الخاص بـWRF-ARW.
- رغم أن عنوان السجل يصف البيانات بأنها GRIB2، فإن الملف `WRF_T2m.grb` الذي جرى تنزيله بدأ برسالة GRIB edition 1 بعد ترويسة WMO النصية؛ لذلك رفضه فحص GRIB2 ولم يُحتسب مصدراً صالحاً لهذا الاختبار.
- جرى اختيار سجل DWD بدلاً منه لأنه يعلن GRIB2 ويتيح ملفاً فعلياً ثبتت رسالة GRIB2 داخله وفكها.

### تحسين إخراج دليل WIS2

- أُصلح توليد نهايات الأسطر في ملفات JSON وSHA256 في commit `656eeae0e6aa558ade72fa8283621f2861fe83b8`.
- إعادة التشغيل `42543144898` بعد الإصلاح اجتازت، وتم تنزيل Artifact وفحصه مستقلاً؛ ملفات JSON سليمة، وmanifest مطابق لبصمة رسالة GRIB2.
