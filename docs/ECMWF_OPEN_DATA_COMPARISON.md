# مصادر البيانات: ECMWF وCPTEC/INPE ETA

## CPTEC/INPE ETA (البرازيل)
يوفر CPTEC/INPE مسارات بيانات لنموذج ETA، وتشمل نطاقات مثل `ams_08km` و`ams_40km` و`ons_40km` و`rjsp_01km`. يختلف استمرار النشر حسب النطاق؛ لذلك لا يفترض التطبيق أن كل نطاق متاح في كل يوم، بل يقرأ فهرس الخادم قبل التنزيل. قد يكون بعض النطاقات مؤرشفاً أو متوقفاً مؤقتاً.

### عرض الملفات المتاحة
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.sources.eta_cptec --date 20261107 --cycle 00 --domain ams_08km --list
```

### تنزيل ملف محدد
انسخ اسم ملف GRIB من نتيجة القائمة:
```powershell
python -m ecmwf_collector.sources.eta_cptec --date 20261107 --cycle 00 --domain ams_08km --file "EXACT_FILE_NAME.grb2" --output downloads/cptec_eta/eta.grb2
```
يُحفظ الملف مؤقتاً بامتداد `.part`، ثم يفحص كـ GRIB وينقل إلى الاسم النهائي عند نجاح الفحص. يُنشأ ملف `.source.json` مع النطاق والدورة والتاريخ والرابط والحجم وSHA-256 وعدد رسائل GRIB.

المصدر الرسمي: https://dataserver.cptec.inpe.br/dataserver_modelos/eta/
معلومات الخدمة الحكومية البرازيلية: https://www.gov.br/pt-br/servicos/obter-dados-provenientes-de-modelos-numericos-de-previsao-de-tempo-inpe-pnt

## ECMWF Open Data والمقارنة مع WMO
- WMO Support Dataset: مصدر الحساب الحالي عبر FTP/FTPS وبيانات اعتماده الخاصة.
- ECMWF Open Data: مجموعة عامة مستقلة للتنبؤات التشغيلية عبر مكتبة `ecmwf-opendata`. لا تستخدم كلمة مرور WMO.

المجموعة العامة لها أرشيف متجدد محدود وليست أرشيفاً تاريخياً كاملاً. راجع شروط الاستخدام والترخيص والإسناد إلى ECMWF قبل إعادة توزيع البيانات.

## التثبيت والتنزيل الانتقائي
```powershell
python -m pip install ecmwf-opendata
$env:PYTHONPATH = "src"
python -m ecmwf_collector.sources.ecmwf_open_data --time 0 --step 24 --param 2t msl --type fc --output downloads/ecmwf_open_data/ifs_00_step24.grib2
```
يمكن تحديد `--date YYYYMMDD` و`--model ifs|aifs-single|aifs-ens` و`--resolution 0p25|0p1` و`--source ecmwf|aws|azure|google`. يلزم تحديد المتغير والخطوة لتجنب تنزيل يوم كامل. تحفظ الأداة ملف `.source.json` يتضمن الطلب والتوقيت والحجم وSHA-256 وعدد الرسائل.

## مقارنة الحقول
```powershell
python -m ecmwf_collector.tools.compare_grib_sources WMO_FILE ECMWF_FILE --output output/source_comparison.json
```
تطابق الحقول بحسب paramId ونوع المستوى ورقمه ووقت الصلاحية. لا تحسب الفروق إلا عند تطابق الشكل وإحداثيات الشبكة والوحدات.

**تمييز علمي أساسي:** سلامة الملف، اكتمال الحقول، تطابق الوقت والشبكة، والاختلاف العددي مؤشرات منفصلة. لا تثبت أي منها وحدها صحة التنبؤ. تقييم الدقة يحتاج رصداً مستقلاً موثوقاً.
