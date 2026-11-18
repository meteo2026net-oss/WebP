"""ECMWF Open Data client; separate from authenticated WMO Support FTP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def available_forecast_steps(model: str, time: int) -> list[int]:
    """Return the published forecast steps for a model and UTC cycle."""
    if time not in (0, 6, 12, 18):
        raise ValueError("دورة ECMWF يجب أن تكون 00 أو 06 أو 12 أو 18 UTC.")
    if model in ("aifs-single", "aifs-ens"):
        return list(range(0, 361, 6))
    if model != "ifs":
        raise ValueError("النموذج غير مدعوم.")
    if time in (6, 18):
        return list(range(0, 91, 3))
    return list(range(0, 145, 3)) + list(range(150, 361, 6))


def validate_forecast_step(model: str, time: int, step: int) -> None:
    """Reject forecast steps that are not published for the selected model and UTC cycle."""
    if int(step) not in available_forecast_steps(model, int(time)):
        raise ValueError(
            f"خطوة التنبؤ {step} ساعة غير متاحة للنموذج {model} ودورة {int(time):02d} UTC."
        )


def build_forecast_steps(model: str, time: int, start: int, end: int) -> list[int]:
    """Build an inclusive, valid forecast-step sequence without requesting unsupported hours."""
    validate_forecast_step(model, time, start)
    validate_forecast_step(model, time, end)
    if end < start:
        raise ValueError("ساعة نهاية التوقع يجب ألا تسبق ساعة البداية.")
    steps = [
        step for step in available_forecast_steps(model, time)
        if int(start) <= step <= int(end)
    ]
    if not steps or steps[0] != int(start) or steps[-1] != int(end):
        raise ValueError("نطاق ساعات التنبؤ لا يطابق خطوات النموذج المتاحة.")
    return steps


def retrieve_open_data(
    request,
    target,
    *,
    source="ecmwf",
    model="ifs",
    resolution="0p25",
    client_factory=None,
    catalog_sink=None,
):
    """Retrieve an explicitly selected subset, validate it, then atomically publish."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not request or "param" not in request or "step" not in request:
        raise ValueError("حدد param وstep صراحةً لتجنب تنزيل مجموعة ضخمة بالخطأ.")
    request = dict(request)
    requested_steps = request["step"]
    if not isinstance(requested_steps, (list, tuple)):
        requested_steps = [requested_steps]
    if not requested_steps:
        raise ValueError("يجب تحديد خطوة تنبؤ واحدة على الأقل.")
    for requested_step in requested_steps:
        validate_forecast_step(model, int(request.get("time", 0)), int(requested_step))
    if model in ("aifs-single", "aifs-ens"):
        if resolution != "0p25":
            raise ValueError("نماذج AIFS متاحة بدقة 0.25° فقط.")
        if model == "aifs-single":
            request.setdefault("stream", "oper")
            request.setdefault("type", "fc")
        else:
            request.setdefault("stream", "enfo")
            request.setdefault("type", "pf")
            number = request.get("number")
            if request["type"] != "pf" or not isinstance(number, int) or not 1 <= number <= 50:
                raise ValueError("AIFS Ensemble يتطلب اختيار عضو واحد من 1 إلى 50 ونوع pf.")
    elif model != "ifs":
        raise ValueError("النموذج غير مدعوم.")
    if client_factory is None:
        try:
            from ecmwf.opendata import Client
        except ImportError as exc:
            raise RuntimeError(
                "ثبّت الحزمة: python -m pip install ecmwf-opendata"
            ) from exc
        client_factory = Client

    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    try:
        client = client_factory(source=source, model=model, resol=resolution)
        result = client.retrieve(request=request, target=str(part))
        if not part.is_file() or not part.stat().st_size:
            raise RuntimeError("لم ينتج المصدر ملفاً غير فارغ.")
        from ecmwf_collector.fileinspect import inspect_file
        check = inspect_file(part)
        if check.verdict != "ok" or check.kind != "grib2":
            raise RuntimeError(f"فشل فحص GRIB2: {check.verdict}: {check.problem}")
        os.replace(part, target)
        actual_datetime = getattr(result, "datetime", None)
        if not request.get("date") and actual_datetime is not None:
            actual_label = actual_datetime.strftime("%Y%m%dT%H")
            actual_target = target.with_name(target.name.replace("latest", actual_label))
            if actual_target != target:
                os.replace(target, actual_target)
                target = actual_target
    except Exception:
        part.unlink(missing_ok=True)
        raise

    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)

    report = {
        "source": "ecmwf_open_data",
        "endpoint": source,
        "model": model,
        "resolution": resolution,
        "request": request,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": (
            f"{request['date']}T{int(request.get('time', 0)):02d}:00:00Z"
            if request.get("date") else None
        ),
        "returned_forecast_datetime": (
            result.datetime.isoformat()
            if getattr(result, "datetime", None) else None
        ),
        "file": target.name,
        "path": str(target.resolve()),
        "size_bytes": target.stat().st_size,
        "sha256": digest.hexdigest(),
        "grib_edition": check.kind,
        "message_count": check.messages,
        "integrity": check.verdict,
    }
    sidecar_path = target.with_suffix(target.suffix + ".source.json")
    sidecar_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if catalog_sink is not None:
        try:
            report["catalog_registration"] = catalog_sink.register_sidecar(sidecar_path)
        except Exception as exc:
            raise RuntimeError(
                f"تم حفظ ملف GRIB وملف المصدر، لكن تعذر تسجيله في الكتالوج: {exc}"
            ) from None
    return report


def main():
    parser = argparse.ArgumentParser(description="تنزيل انتقائي من ECMWF Open Data")
    parser.add_argument("--date")
    parser.add_argument("--time", type=int, choices=(0, 6, 12, 18), default=0)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--param", nargs="+", required=True)
    parser.add_argument("--type", default="fc", choices=("fc", "pf", "cf", "em", "es"))
    parser.add_argument("--model", default="ifs", choices=("ifs", "aifs-single", "aifs-ens"))
    parser.add_argument("--resolution", default="0p25", choices=("0p25", "0p1"))
    parser.add_argument("--source", default="ecmwf", choices=("ecmwf", "aws", "azure", "google"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = {
        "time": args.time,
        "step": args.step,
        "param": args.param,
        "type": args.type,
    }
    if args.date:
        request["date"] = args.date
    if args.model == "aifs-ens":
        request.update({"stream": "enfo", "type": "pf", "number": 1})
    elif args.model == "aifs-single":
        request["stream"] = "oper"
    print(json.dumps(
        retrieve_open_data(
            request, args.output, source=args.source,
            model=args.model, resolution=args.resolution,
        ),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
