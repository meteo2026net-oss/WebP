"""ECMWF Open Data client; separate from authenticated WMO Support FTP."""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

def retrieve_open_data(request, target, *, source="ecmwf", model="ifs", resolution="0p25", client_factory=None, catalog_sink=None):
    """Retrieve an explicitly selected subset, validate it, then atomically publish."""
    target=Path(target); target.parent.mkdir(parents=True,exist_ok=True)
    if not request or "param" not in request or "step" not in request:
        raise ValueError("حدد param وstep صراحةً لتجنب تنزيل مجموعة ضخمة بالخطأ.")
    if client_factory is None:
        try: from ecmwf.opendata import Client
        except ImportError as exc:
            raise RuntimeError("ثبّت الحزمة: python -m pip install ecmwf-opendata") from exc
        client_factory=Client
    part=target.with_name(target.name+".part"); part.unlink(missing_ok=True)
    try:
        client=client_factory(source=source,model=model,resol=resolution)
        result=client.retrieve(request=request,target=str(part))
        if not part.is_file() or not part.stat().st_size: raise RuntimeError("لم ينتج المصدر ملفاً غير فارغ.")
        from ecmwf_collector.fileinspect import inspect_file
        check=inspect_file(part)
        if check.verdict!="ok" or not check.kind.startswith("grib"):
            raise RuntimeError(f"فشل فحص GRIB: {check.verdict}: {check.problem}")
        os.replace(part,target)
    except Exception:
        part.unlink(missing_ok=True); raise
    h=hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b""): h.update(chunk)
    report={"source":"ecmwf_open_data","endpoint":source,"model":model,"resolution":resolution,
      "request":request,"retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
      "returned_forecast_datetime":getattr(result,"datetime",None).isoformat() if getattr(result,"datetime",None) else None,
      "file":target.name,"size_bytes":target.stat().st_size,"sha256":h.hexdigest(),
      "grib_edition":check.kind,"message_count":check.messages,"integrity":check.verdict}
    sidecar_path = target.with_suffix(target.suffix+".source.json")
    sidecar_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if catalog_sink is not None:
        report["catalog_registration"] = catalog_sink.register_sidecar(sidecar_path)
    return report

def main():
    p=argparse.ArgumentParser(description="تنزيل انتقائي من ECMWF Open Data")
    p.add_argument("--date"); p.add_argument("--time",type=int,choices=(0,6,12,18),default=0)
    p.add_argument("--step",type=int,required=True); p.add_argument("--param",nargs="+",required=True)
    p.add_argument("--type",default="fc",choices=("fc","pf","cf","em","es"))
    p.add_argument("--model",default="ifs",choices=("ifs","aifs-single","aifs-ens"))
    p.add_argument("--resolution",default="0p25",choices=("0p25","0p1"))
    p.add_argument("--source",default="ecmwf",choices=("ecmwf","aws","azure","google"))
    p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    req={"time":a.time,"step":a.step,"param":a.param,"type":a.type}
    if a.date: req["date"]=a.date
    print(json.dumps(retrieve_open_data(req,a.output,source=a.source,model=a.model,resolution=a.resolution),ensure_ascii=False,indent=2))
if __name__=="__main__": main()
