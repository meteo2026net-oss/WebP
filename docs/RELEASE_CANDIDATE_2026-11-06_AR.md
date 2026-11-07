# سجل إصدار مرشح — 6 نوفمبر 2026

## حزمة Windows x64 الأحدث

- الاسم: `ECMWFWebP-Windows-x64`
- الحجم: 150702869 بايت (نحو 150.7 MB)
- Artifact ID: `13539074610`
- رابط التنزيل: https://github.com/meteo2026net-oss/WebP/actions/runs/42292635305/artifacts/13539074610
- تاريخ الإنشاء: 2026-11-06 20:54:55 UTC
- تاريخ انتهاء صلاحية Artifact: 2026-11-20 21:01:04 UTC
- SHA-256 للحزمة ZIP: `98919303a180d2c5e78406135ecb1a4a2bee6bbff41e3e6f7c4e5a1e4b32ee90`

## مصدر البناء

- المستودع: `meteo2026net-oss/WebP`
- الفرع: `feat/windows-one-click-desktop-package`
- الالتزام: `9337c500c4061f8e6696e24b10a58acc91012be4`
- سجل Windows Actions: https://github.com/meteo2026net-oss/WebP/actions/runs/42292635305
- سجل اختبارات Python: https://github.com/meteo2026net-oss/WebP/actions/runs/42292635419

## ما اجتازته هذه النسخة آلياً

- تجميع مصادر Python.
- **323 اختبار وحدة ناجحاً**.
- إنشاء مجلد البرنامج التنفيذي باستخدام PyInstaller والتحقق من وجود EXE.
- تجهيز مشغّل التشغيل وأداة القبول المحمولة.
- إنشاء manifest لبصمات SHA-256.
- فحص قبول الحزمة المعبأة.
- التحقق من تغطية manifest وصحة البصمات.
- رفع ZIP إلى GitHub Actions Artifacts.

## حدود الاعتماد

نجاح CI وفحص الحزمة لا يثبتان بعد نجاح الاتصال بحساب ECMWF الخاص بالمستخدم أو تشغيل PostgreSQL على جهازه. يلزم إكمال قائمة القبول الميداني في [WINDOWS_FINAL_ACCEPTANCE_AR.md](WINDOWS_FINAL_ACCEPTANCE_AR.md)، خصوصاً تنزيل ملف اختبار حقيقي وتجربة النسخ الاحتياطي والاستعادة والترحيل على قاعدة اختبار.

هذه حزمة مرشح إصدار موثقة، وليست إعلان اعتماد ميداني نهائي.
