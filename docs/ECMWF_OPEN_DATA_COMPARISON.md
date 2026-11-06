# ECMWF Open Data والمقارنة مع WMO

## المصدران
- WMO Support Dataset: مصدر الحساب الحالي عبر FTP/FTPS وبيانات اعتماده الخاصة.
- ECMWF Open Data: مجموعة عامة مستقلة للتنبؤات التشغيلية عبر مكتبة `ecmwf-opendata`. لا تستخدم كلمة مرور WMO.

المجموعة العامة لها أرشيف متجدد محدود وليست أرشيفاً تاريخياً كاملاً. راجع شروط الاستخدام والترخيص والإسناد إلى ECMWF قبل إعادة توزيع البيانات.

## التثبيت والتنزيل الانتقائي
```powershell
python -m pip install ecmwf-opendata
$env:PYTHONPATH = "src"
python -m ecmwf_collector.sources.ecmwf_open_data --time 0 --step 24 --param 2t msl --type fc --output downloads/ecmwf_open_data/ifs_00_step24.grib2
```
يمكن تحديد `--date YYYYMMDD` و`--model ifs|aifs-single|aifs-ens` و`--resolution 0p25|0p1` و`--source ecmwf|aws|azure|google`. يلزم تحديد المتغير والخطوة لتجنب تنزيل يوم كامل (قد يكون ضخماً جداً). تحفظ الأداة ملف `.source.json` يتضمن الطلب والتوقيت والحجم وSHA-256 وعدد الرسائل، ولا تنشر الملف النهائي إلا بعد فحص GRIB.

## مقارنة الحقول
```powershell
python -m ecmwf_collector.tools.compare_grib_sources WMO_FILE ECMWF_FILE --output output/source_comparison.json
```
تطابق الحقول بحسب paramId ونوع المستوى ورقمه ووقت الصلاحية. لا تحسب الفروق إلا عند تطابق الشكل وإحداثيات الشبكة والوحدات. التقرير يعرض التغطية المشتركة والانحياز وMAE وRMSE وأقصى فرق والارتباط والحقول غير المتطابقة.

**تمييز علمي أساسي:** سلامة الملف، اكتمال الحقول، تطابق الوقت والشبكة، والاختلاف العددي مؤشرات منفصلة. لا تثبت أي منها وحدها صحة التنبؤ. تقييم الدقة يحتاج رصداً مستقلاً موثوقاً، مع تطابق المكان والوقت والوحدة ومراعاة تمثيل المحطة مقابل خلية الشبكة.
