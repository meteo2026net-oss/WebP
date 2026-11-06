# سجل إصدار مرشح — 6 نوفمبر 2026

## حزمة Windows x64 الأحدث

- الاسم: `ECMWFWebP-Windows-x64`
- الحجم: 150703282 بايت (نحو 150.7 MB)
- Artifact ID: `13540102605`
- رابط التنزيل: https://github.com/meteo2026net-oss/WebP/actions/runs/42291850228/artifacts/13540102605
- تاريخ الإنشاء: 2026-11-06 20:54:55 UTC
- تاريخ انتهاء صلاحية Artifact: 2026-11-20 20:54:43 UTC
- SHA-256 للحزمة ZIP: `7241ff1ee9d6027ad8e880eb4f418b5b2ff6c460f3186d54726e13893d7de534`

## مصدر البناء

- المستودع: `meteo2026net-oss/WebP`
- الفرع: `feat/windows-one-click-desktop-package`
- الالتزام: `de76cbd237191d471946e7785c1c03947823d309`
- سجل Windows Actions: https://github.com/meteo2026net-oss/WebP/actions/runs/42291850228
- سجل اختبارات Python: https://github.com/meteo2026net-oss/WebP/actions/runs/42291850400

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
