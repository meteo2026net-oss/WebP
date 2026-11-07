"""User-facing startup and recovery messages."""


def postgres_recovery_details(exc: Exception, environment_dsn: bool, redact) -> str:
    """Build safe, readable PostgreSQL recovery details for the startup dialog."""
    details = (
        f"السبب: {type(exc).__name__}: {redact(str(exc))}\n\n"
        "تحقق من تشغيل خدمة PostgreSQL وصحة إعداد الاتصال."
    )
    if environment_dsn:
        details += (
            "\n\nمصدر الاتصال هو متغير البيئة ECMWF_POSTGRES_DSN؛ "
            "سيبقى كما هو، وسيؤدي اختيار SQLite إلى تجاوز PostgreSQL لهذه الجلسة فقط."
        )
    else:
        details += (
            "\n\nيمكنك استخدام SQLite لهذه الجلسة فقط، أو إزالة اتصال PostgreSQL "
            "المحفوظ من مخزن بيانات اعتماد Windows والعودة إلى SQLite بشكل دائم."
        )
    return details
