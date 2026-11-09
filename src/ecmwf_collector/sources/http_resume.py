"""Resumable HTTP downloads with validator-aware byte ranges and retry policy."""
from __future__ import annotations
import hashlib, json, os, re, time, urllib.error, urllib.request
from pathlib import Path

class HttpResumeError(RuntimeError):
    """Unsafe or inconsistent HTTP range response."""

def _headers(response):
    return getattr(response, "headers", {}) or {}

def download_resumable(url: str, part_path: Path, *, timeout: float,
                       opener=urllib.request.urlopen, chunk_size: int = 1024 * 1024) -> str:
    part_path=Path(part_path); checkpoint=part_path.with_suffix(part_path.suffix+".resume.json")
    part_path.parent.mkdir(parents=True,exist_ok=True); state={}
    if part_path.exists() and checkpoint.exists():
        try: state=json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError,ValueError): state={}
    offset=part_path.stat().st_size if part_path.exists() else 0
    if not state or state.get("url")!=url:
        offset=0; part_path.unlink(missing_ok=True); checkpoint.unlink(missing_ok=True)
    headers={}
    if offset:
        headers["Range"]=f"bytes={offset}-"
        validator=state.get("etag") or state.get("last_modified")
        if validator: headers["If-Range"]=validator
    request=urllib.request.Request(url,headers=headers); digest=hashlib.sha256()
    if offset:
        with part_path.open("rb") as old:
            for chunk in iter(lambda:old.read(chunk_size),b""): digest.update(chunk)
    response=opener(request,timeout=timeout)
    with response:
        status=getattr(response,"status",None)
        if status is None:
            try: status=response.getcode()
            except (AttributeError,TypeError): status=200
        rh=_headers(response); append=bool(offset and status==206)
        if append:
            match=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)",rh.get("Content-Range","").strip())
            if not match or int(match.group(1))!=offset: raise HttpResumeError("HTTP Range offset mismatch")
        else: digest=hashlib.sha256()
        saved={"url":url,"etag":rh.get("ETag") or (state.get("etag") if append else None),
               "last_modified":rh.get("Last-Modified") or (state.get("last_modified") if append else None)}
        tmp=checkpoint.with_suffix(checkpoint.suffix+".tmp")
        tmp.write_text(json.dumps(saved),encoding="utf-8"); os.replace(tmp,checkpoint)
        with part_path.open("ab" if append else "wb") as target:
            while True:
                chunk=response.read(chunk_size)
                if not chunk: break
                target.write(chunk); digest.update(chunk)
            target.flush(); os.fsync(target.fileno())
    if status==206:
        match=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)",_headers(response).get("Content-Range","").strip())
        if not match: raise HttpResumeError("HTTP 206 missing Content-Range")
        total=None if match.group(3)=="*" else int(match.group(3))
        if total is not None and part_path.stat().st_size!=total: raise HttpResumeError("Incomplete HTTP range")
    else:
        length=_headers(response).get("Content-Length")
        if length and part_path.stat().st_size!=int(length): raise HttpResumeError("Content-Length mismatch")
    return digest.hexdigest()

def download_resumable_with_retry(url: str, part_path: Path, *, timeout: float,
        opener=urllib.request.urlopen, max_attempts: int=5, base_delay: float=1.0,
        max_delay: float=30.0, sleeper=time.sleep, on_retry=None) -> str:
    """Retry transient transport and HTTP 408/429/5xx failures with bounded backoff."""
    if isinstance(max_attempts,bool) or not isinstance(max_attempts,int) or max_attempts<1:
        raise ValueError("max_attempts must be a positive integer")
    if base_delay<0 or max_delay<0: raise ValueError("retry delays cannot be negative")
    for attempt in range(1,max_attempts+1):
        try:
            return download_resumable(url,part_path,timeout=timeout,opener=opener)
        except urllib.error.HTTPError as exc:
            if exc.code not in {408,429,500,502,503,504} or attempt==max_attempts: raise
            error=exc
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as exc:
            if attempt==max_attempts: raise
            error=exc
        delay=min(max_delay,base_delay*(2**(attempt-1)))
        if on_retry is not None: on_retry(attempt,max_attempts,delay,error)
        sleeper(delay)
    raise RuntimeError("unreachable retry state")

def clear_resume_state(part_path: Path) -> None:
    part_path=Path(part_path); part_path.unlink(missing_ok=True)
    part_path.with_suffix(part_path.suffix+".resume.json").unlink(missing_ok=True)
