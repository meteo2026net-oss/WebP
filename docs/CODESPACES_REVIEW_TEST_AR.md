# بيئة اختبار مراجعة المتنبئين عبر GitHub Codespaces

بيئة اختبار مؤقتة ومعزولة، وليست إنتاجية. لا تستخدم بيانات أرصاد حقيقية أو حسابات المؤسسة.

## 1. فتح Codespace

1. افتح المستودع ثم اختر **Code → Codespaces → Create codespace on feat/windows-one-click-desktop-package**.
2. انتظر اكتمال إعداد الحاوية وتثبيت اعتماديات Python.
3. افتح Terminal داخل Codespaces.

لا تحتاج إلى تثبيت Docker Desktop على Windows؛ يتم تشغيل الخدمات داخل Codespace.

## 2. تشغيل الخدمات وقاعدة البيانات

```bash
bash scripts/start-review-stack.sh
bash scripts/bootstrap-review-db.sh
```

ينشئ المشغّل شهادات اختبار محلية لمدة 30 يوماً وكلمات مرور عشوائية في ملف `.env` الخاص بالـ Codespace. لا ترفع هذا الملف أو الشهادات إلى GitHub.

## 3. إنشاء حسابات الاختبار آلياً

```bash
bash scripts/create-review-test-users.sh
```

ينشئ أربعة حسابات: `test-reviewer` و`test-review_lead` و`test-publisher` و`test-admin`، ويضبط سمة الدور المطلوبة. كلمات المرور العشوائية تحفظ محلياً في `.env` ولا تُطبع في الطرفية.

## 4. تشغيل Review API

```bash
bash scripts/run-review-api.sh
```

من تبويب Ports في Codespaces، اترك المنافذ 8000 و8081 خاصة (Private)، ولا تفتح منفذ PostgreSQL 5432 للعامة. يستخدم Keycloak عنوان HTTPS الذي يوفره تمرير منافذ Codespaces.

## 5. إعداد تطبيق Windows

في تبويب مراجعة المتنبعين أدخل:
- API Base URL: `https://<CODESPACE_NAME>-8000.app.github.dev`
- OIDC Issuer: `https://<CODESPACE_NAME>-8081.app.github.dev/realms/weather-review`
- Public Client ID: `ecmwf-webp-desktop`

استبدل `<CODESPACE_NAME>` باسم Codespace الفعلي. لا يوجد Client Secret. لا تحفظ Access Token أو Refresh Token في التطبيق.

**قيد مهم:** روابط Codespaces الخاصة محمية بتسجيل دخول GitHub. قد لا يستطيع تطبيق Windows المستقل الوصول إليها مباشرةً من دون مصادقة Codespaces. إذا ظهر رفض من بوابة GitHub قبل وصول الطلب إلى Keycloak أو API، فهذا لا يثبت فشل OIDC. لا تجعل المنافذ عامة لمجرد تجاوز هذا الحاجز؛ نحتاج عندها إلى مسار HTTPS تجريبي مناسب أو تنفيذ اختبار API داخل Codespace أولاً.

## 6. دورة القبول المطلوبة

1. سجّل الدخول بحساب `test-reviewer`.
2. تحقق من ظهور حالة الحقل التجريبي في قائمة المراجعات بعد إسنادها.
3. سجّل الدخول بحساب `test-review_lead` وأسند الحالة إلى subject الخاص بالمراجع.
4. افتح المراجعة وأضف تعليقاً.
5. اعتمد الحقل مع سبب واضح.
6. سجّل الخروج ثم الدخول بحساب `test-publisher`.
7. تحقق من ظهور الحقل في قائمة النشر.
8. تحقق من رفض وصول publisher إلى قائمة المراجعات ورفض وصول reviewer إلى قائمة النشر.

## ملاحظات وحدود

- PostgreSQL 16 + PostGIS يستخدم TLS بشهادة اختبار محلية و`sslmode=verify-full`.
- Keycloak يعمل بوضع التطوير، وليس إعداداً إنتاجياً.
- إغلاق Codespace أو حذفه يوقف البيئة.
- لا تعتبر دورة العمل مكتملة حتى تنجح فعلياً من تطبيق Windows وتُراجع استجابات API ونتيجة قاعدة البيانات.
