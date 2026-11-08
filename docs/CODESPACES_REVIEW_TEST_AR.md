# بيئة اختبار مراجعة المتنبئين عبر GitHub Codespaces

هذه بيئة تطوير واختبار مؤقتة ومعزولة، وليست بيئة إنتاج. لا تستخدم بيانات أرصاد حقيقية أو حسابات المؤسسة.

## 1. فتح Codespace

1. افتح المستودع ثم اختر **Code → Codespaces → Create codespace on feat/windows-one-click-desktop-package**.
2. انتظر اكتمال إعداد الحاوية وتثبيت اعتماديات Python.
3. افتح Terminal داخل Codespaces.

لا تحتاج إلى تثبيت Docker Desktop على Windows؛ ميزة Docker-in-Docker تعمل داخل بيئة Codespaces السحابية.

## 2. تشغيل الخدمات

نفّذ:

```bash
bash scripts/start-review-stack.sh
bash scripts/bootstrap-review-db.sh
```

ينشئ المشغّل شهادة CA وشهادة PostgreSQL محليتين لمدة 30 يوماً، وكلمات مرور عشوائية في ملف `.env` ذي صلاحيات مقيدة. الملفات والشهادات غير مخصصة للرفع إلى GitHub.

خدمات الاختبار:
- PostgreSQL 16 + PostGIS على المنفذ 5432، مع TLS.
- Keycloak على المنفذ 8081.
- Review API سيعمل لاحقاً على المنفذ 8000.

اترك المنفذين 8081 و5432 خاصين. لا تجعل منفذ قاعدة البيانات عاماً.

## 3. إعداد حسابات Keycloak

بعد أن تصبح خدمة Keycloak جاهزة، افتح منفذ 8081 من تبويب Ports عبر رابط HTTPS الخاص بـ Codespaces. سجّل الدخول ببيانات المدير الموجودة في ملف `.env` المحلي داخل Codespace.

استورد ملف realm `.devcontainer/keycloak/weather-review-realm.json` تلقائياً عند أول تشغيل. ينشئ realm باسم `weather-review` وعميل Native/Public باسم `ecmwf-webp-desktop` مع Authorization Code وPKCE، وعنوان رجوع loopback، وخرائط audience و`review_role`.

أنشئ أربعة مستخدمين تجريبيين من لوحة Keycloak، واضبط لكل مستخدم سمة (User Attribute) باسم `review_role` وقيمة واحدة من:
- `reviewer`
- `review_lead`
- `publisher`
- `admin`

فعّل لكل مستخدم كلمة مرور اختبار غير مؤقتة. لا تستخدم كلمة مرورك الشخصية.

## 4. تشغيل Review API

من Terminal داخل Codespaces حمّل متغيرات البيئة:

```bash
set -a
source .env
set +a
export ECMWF_REVIEW_DATABASE_DSN="host=127.0.0.1 port=5432 dbname=weather_review user=review_api password=$API_DB_PASSWORD sslmode=verify-full sslrootcert=$PWD/.devcontainer/certs/ca.crt"
export ECMWF_OIDC_ISSUER="https://$CODESPACE_NAME-8081.app.github.dev/realms/weather-review"
export ECMWF_OIDC_AUDIENCE="review-api"
export ECMWF_OIDC_JWKS_URL="$ECMWF_OIDC_ISSUER/protocol/openid-connect/certs"
export ECMWF_OIDC_ROLE_CLAIM="review_role"
export ECMWF_OIDC_ROLE_MAPPING='{"reviewer":"reviewer","review_lead":"review_lead","publisher":"publisher","admin":"admin"}'
gunicorn --bind 0.0.0.0:8000 --workers 2 scripts.review_api_dev:application
```

يجب أن يعرض Codespaces منفذ 8000 كرابط HTTPS خاص. لا تنشر المنفذ للعامة.

## 5. إعداد تطبيق Windows

في تبويب مراجعة المتنبئين أدخل:
- API Base URL: رابط HTTPS لمنفذ 8000.
- OIDC Issuer: رابط HTTPS لمنفذ 8081 متبوعاً بـ `/realms/weather-review`.
- Public Client ID: `ecmwf-webp-desktop`.

لا يوجد Client Secret. لا تحفظ Access Token أو Refresh Token في التطبيق.

## 6. دورة القبول

1. سجّل الدخول بحساب reviewer.
2. اختبر قائمة المراجعات؛ يجب أن تظهر حالة الحقل التجريبي.
3. سجّل الدخول بحساب review_lead وأسند الحالة إلى المراجع.
4. افتح المراجعة وأضف تعليقاً.
5. اعتمد الحقل مع سبب واضح.
6. سجّل الخروج ثم الدخول بحساب publisher.
7. افتح قائمة النشر وتحقق من ظهور الحقل المعتمد.
8. تحقق أن publisher لا يستطيع قراءة قائمة المراجعات، وأن reviewer لا يستطيع قراءة قائمة النشر.

## ملاحظات أمان وحدود

- هذه بيئة تطوير فقط؛ Keycloak يعمل بوضع التطوير خلف HTTPS الذي يوفّره تمرير منافذ Codespaces.
- PostgreSQL يستخدم شهادة اختبار محلية ويشترط `sslmode=verify-full`.
- بيانات الاعتماد في `.env` مؤقتة ومولدة محلياً، ويجب عدم نسخها إلى المحادثة أو Git.
- إغلاق Codespace أو حذفه يوقف البيئة؛ لا تعتمد عليها لتخزين بيانات دائمة.
- لا تعتبر دورة العمل ناجحة حتى تُنفّذ فعلياً من تطبيق Windows وتُراجع سجلات API ونتيجة قاعدة البيانات.
