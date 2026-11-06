# سجل إصدار مرشح — 6 نوفمبر 2026

## حزمة Windows x64

- الاسم: `ECMWFWebP-Windows-x64`
- الحجم: 150,700,661 بايت (نحو 150.7 MB)
- Artifact ID: `13467770351`
- رابط التنزيل: https://github.com/meteo2026net-oss/WebP/actions/runs/42138888231
- تاريخ الإنشاء: 2026-11-06 00:47:47 UTC
- تاريخ انتهاء صلاحية Artifact: 2026-11-20 00:47:38 UTC
- SHA-256: `4825859f69d030b4acb76f730f30c344cc1b511caa6551a5f1fafa51617a6612`

## مصدر البناء

- المستودع: `meteo2026net-oss/WebP`
- الفرع: `feat/windows-one-click-desktop-package`
- الالتزام: `fec7bc7c5775d8b3b82a0421834d676b7d623911`
- سجل Windows Actions: https://github.com/meteo2026net-oss/WebP/actions/runs/42138888231
- سجل اختبارات Python: https://github.com/meteo2026net-oss/WebP/actions/runs/42138888278

## ما اجتازته هذه النسخة آلياً

- تجميع مصادر Python.
- اختبارات الوحدة على Windows.
- إنشاء مجلد البرنامج التنفيذي باستخدام PyInstaller.
- التحقق من وجود الملف التنفيذي.
- تجهيز مشغّل التشغيل وأداة القبول المحمولة.
- إنشاء manifest لبصمات SHA-256.
- فحص قبول الحزمة المعبأة.
- التحقق من تغطية manifest وصحة البصمات.
- رفع ZIP إلى GitHub Actions Artifacts.

## حدود الاعتماد

نجاح CI وفحص الحزمة لا يثبتان بعد نجاح الاتصال بحساب ECMWF الخاص بالمستخدم أو تشغيل PostgreSQL على جهازه. يلزم إكمال قائمة القبول الميداني في [WINDOWS_FINAL_ACCEPTANCE_AR.md](WINDOWS_FINAL_ACCEPTANCE_AR.md)، خصوصاً تنزيل ملف اختبار حقيقي وتجربة النسخ الاحتياطي والاستعادة والترحيل على قاعدة اختبار.

هذه حزمة مرشح إصدار موثقة، وليست إعلان اعتماد ميداني نهائي.
