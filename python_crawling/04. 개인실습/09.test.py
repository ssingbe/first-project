# -*- coding: utf-8 -*-
"""
Universal YouTube Downloader – Final (robust, all-sites compatible)
- 실행 시 GUI 자동 실행
- 실행마다 yt-dlp 자동 업데이트
- [가용-품질-조회] → 실제 가능한 해상도로 콤보 자동 구성(초기 비활성화)
- 해상도 선택 로직(전역 호환): (bestvideo[>=선택]+bestaudio) → (bestvideo+bestaudio) → progressive(best)
- 진행률 막대 + % + 속도 + ETA
- 다운로드 완료 후 실제 해상도/FPS/코덱/용량 표기 (ffprobe)
- 여러 URL: 멀티라인 입력 / TXT 불러오기
- 자막 SRT + UTF-8 BOM(윈도우 메모장 한글 깨짐 방지)
- 컨테이너: Auto(권장) / mp4 / mkv
- 프록시/쿠키 도움말 버튼
"""

import sys, re, threading, shutil, subprocess, json
from pathlib import Path
from datetime import datetime

# ---------- 0) yt-dlp 자동 최신화 ----------
def ensure_yt_dlp_updated():
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

ensure_yt_dlp_updated()
try:
    import yt_dlp
except Exception as e:
    print("yt-dlp-임포트-실패-인터넷/권한-확인-", e)
    sys.exit(1)

# ---------- 유틸 ----------
ILLEGAL = r'[\\/*?:"<>|]'
def safe_name(s: str) -> str:
    s = re.sub(ILLEGAL, "-", s).strip()
    return s or f"video-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

def human(n: float) -> str:
    try:
        n = float(n)
    except Exception:
        return "0"
    for unit in ["", "K", "M", "G", "T"]:
        if abs(n) < 1024:
            return f"{n:3.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"

# ---------- 자막 BOM 변환 ----------
def _to_utf8_bom(path: Path):
    try:
        if path.suffix.lower() == ".srt" and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            path.write_text(text, encoding="utf-8-sig")  # UTF-8 with BOM
    except Exception:
        pass

def _convert_all_srt_to_bom(folder: Path):
    for srt in folder.rglob("*.srt"):
        _to_utf8_bom(srt)

# ---------- 진행률 콜백 ----------
def progress_hook_factory(on_progress=None, on_log=None):
    def hook(d):
        try:
            status = d.get("status")
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            percent = (done / total * 100) if total else 0.0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            if status == "downloading":
                if on_progress:
                    on_progress(percent, speed, eta, total, done)
            elif status == "finished":
                if on_progress:
                    on_progress(100.0, speed, 0, total, total)
                if on_log:
                    on_log("다운로드-완료-병합-중...\n")
        except Exception:
            pass
    return hook

# ---------- 선택값 → yt-dlp 포맷 문자열 (전역 호환형) ----------
def build_format_expr(height_choice: str, audio_only: bool):
    """
    모든 사이트/영상 유형에서 일관적으로 동작:
    1) (분리스트림) bestvideo[height>=선택] + bestaudio
    2) (분리스트림) bestvideo + bestaudio
    3) (프로그레시브) best
    """
    if audio_only:
        return "bestaudio/best"

    height_map = {
        "최고": None, "2160p": 2160, "1440p": 1440, "1080p": 1080,
        "720p": 720, "480p": 480, "360p": 360
    }
    key = (height_choice or "최고").replace(" ★", "")
    h = height_map.get(key, None)

    if h is None:
        return "bestvideo+bestaudio/best"

    # 단계적 시도: >=선택 → 임의의 bestvideo → progressive
    return f"(bestvideo[height>={h}]+bestaudio)/best"

# ---------- 가용 포맷/해상도 조회 ----------
def fetch_available_heights(url: str, proxy: str = None, cookies: Path = None):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False,
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    if cookies and cookies.exists():
        ydl_opts["cookiefile"] = str(cookies)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    heights = set()
    for f in (info.get("formats") or []):
        h = f.get("height")
        if isinstance(h, int) and h > 0:
            heights.add(h)
    return sorted(heights, reverse=True), info

def dump_format_table(info, on_log):
    """포맷 테이블을 로그로 표시(디버그/확인용)"""
    fmts = info.get("formats") or []
    if not on_log:
        return
    rows = []
    for f in fmts:
        h = f.get("height")
        if not h:
            continue
        rid = f.get("format_id")
        ext = f.get("ext")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        fps = f.get("fps") or ""
        tbr = f.get("tbr")
        rows.append((h, rid, ext, vcodec, acodec, fps, tbr))
    rows.sort(reverse=True)
    on_log("가용 포맷 목록(높은 해상도 우선 최대 30개):\n")
    on_log("height | id | ext | vcodec | acodec | fps | tbr(kbps)\n")
    for h, rid, ext, vcodec, acodec, fps, tbr in rows[:30]:
        on_log(f"{h:>4}p | {rid} | {ext} | {vcodec} | {acodec} | {fps} | {tbr}\n")

# ---------- ffprobe로 실제 영상 정보 읽기 ----------
def ffprobe_video_info(filepath: Path):
    """width, height, fps(float), vcodec 문자열 | 실패 시 None"""
    try:
        if shutil.which("ffprobe") is None:
            return None
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,codec_name",
            "-of", "json", str(filepath)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams", [])
        if not streams:
            return None
        st = streams[0]
        w = int(st.get("width") or 0)
        h = int(st.get("height") or 0)
        codec = st.get("codec_name") or ""
        afr = st.get("avg_frame_rate") or "0/1"
        try:
            num, den = afr.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 0.0
        except Exception:
            fps = 0.0
        return w, h, fps, codec
    except Exception:
        return None

# ---------- 다운로드 ----------
def download(
    url: str,
    outdir: Path,
    format_expr: str,
    container_choice: str = "auto",   # auto/mp4/mkv
    subtitle: bool = True,
    subtitle_langs: str = "ko,en",
    thumb: bool = False,
    rate_limit: str = None,
    retries: int = 10,
    proxy: str = None,
    cookies: Path = None,
    on_progress=None,
    on_log=None,
):
    outdir.mkdir(parents=True, exist_ok=True)

    # 컨테이너 정책: auto면 yt-dlp/ffmpeg가 자동 결정 (가장 호환되는 컨테이너)
    merge_format = None if (container_choice or "auto").lower() == "auto" else container_choice.lower()

    ydl_opts = {
        "paths": {"home": str(outdir)},
        "outtmpl": {"default": "%(title).180s-%(id)s.%(ext)s"},
        "format": format_expr,
        "merge_output_format": merge_format,
        "noprogress": True,  # 콘솔 진행률 숨김(우리 막대만 표시)
        "ignoreerrors": "only_download",
        "retries": retries,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,
        "progress_hooks": [progress_hook_factory(on_progress, on_log)],
        # 선택 안정화 힌트
        "prefer_free_formats": False,                          # mp4 가능 시 선호
        "format_sort": ["res", "fps", "codec:av1,hevc,h264,vp9"],
        "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
    }

    # 자막/썸네일
    postprocessors = [
        {"key": "FFmpegMetadata"},
        {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
    ]
    if merge_format:  # mp4/mkv 강제일 때만 remuxer 고정
        postprocessors.insert(0, {"key": "FFmpegVideoRemuxer", "preferedformat": merge_format})

    if subtitle:
        ydl_opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [s.strip() for s in subtitle_langs.split(",") if s.strip()],
            "subtitlesformat": "srt",
        })
    if thumb:
        ydl_opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    ydl_opts["postprocessors"] = postprocessors

    if rate_limit:
        ydl_opts["ratelimit"] = rate_limit
    if proxy:
        ydl_opts["proxy"] = proxy
    if cookies and cookies.exists():
        ydl_opts["cookiefile"] = str(cookies)

    if shutil.which("ffmpeg") is None and on_log:
        on_log("⚠-FFmpeg-미설치/PATH-미등록-병합/자막-처리-제한-가능성\n")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    _convert_all_srt_to_bom(outdir)

    # 저장된 파일 경로 추정
    output_file = None
    try:
        if "requested_downloads" in info and info["requested_downloads"]:
            output_file = Path(info["requested_downloads"][0]["_filename"])
        elif info.get("_filename"):
            output_file = Path(info["_filename"])
        else:
            candidates = sorted(outdir.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                output_file = candidates[0]
    except Exception:
        pass

    # 선택된 포맷 로깅
    try:
        if on_log:
            req = info.get("requested_formats") or []
            if req:
                vf = req[0]; af = req[1] if len(req) > 1 else {}
                on_log(f"선택된-비디오: id={vf.get('format_id')} {vf.get('vcodec')} {vf.get('width')}x{vf.get('height')} {vf.get('fps')}fps\n")
                if af:
                    on_log(f"선택된-오디오: id={af.get('format_id')} {af.get('acodec')} ~{af.get('abr')}kbps\n")
            else:
                on_log(f"선택된-포맷: id={info.get('format_id')} {info.get('vcodec')} {info.get('width')}x{info.get('height')} (progressive)\n")
    except Exception:
        pass

    # 실제 파일 정보
    w=h=fps=codec=None
    if output_file and output_file.exists():
        vi = ffprobe_video_info(output_file)
        if vi:
            w, h, fps, codec = vi

    # 메타 폴백
    if (w is None or h is None) and isinstance(info, dict):
        h = h or info.get("height") or (info.get("requested_formats") or [{}])[0].get("height")
        w = w or info.get("width")

    size_mb = None
    if output_file and output_file.exists():
        try:
            size_mb = output_file.stat().st_size / (1024*1024)
        except Exception:
            pass

    return info, output_file, w, h, fps, codec, size_mb

# ---------- GUI ----------
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    available_heights = []  # e.g., [2160,1440,1080...]

    root = tk.Tk()
    root.title("Universal-YouTube-Downloader")
    root.geometry("1000x720")

    # ---- 로그 도우미 ----
    def log(msg: str):
        txt.configure(state="normal")
        txt.insert(tk.END, msg)
        txt.see(tk.END)
        txt.configure(state="disabled")

    def pick_heights_into_combo(hlist):
        # 조회된 해상도로만 구성 + "최고"
        items = ["최고"] + [f"{h}p" for h in hlist]
        res_combo["values"] = items
        if items:
            res_combo.current(0)
        res_combo.configure(state="readonly")

    # ---- 진행률 업데이트 ----
    def on_progress(percent, speed, eta, total, done):
        pb["value"] = max(0.0, min(100.0, percent))
        percent_txt = f"{percent:5.1f}%"
        speed_txt = f"{human(speed)}/s" if speed else "-"
        eta_txt = f"{int(eta)}s" if eta else "-"
        size_txt = f"{human(done)}/{human(total)}" if total else "-"
        prog_label_var.set(f"{percent_txt}  |  {size_txt}  |  {speed_txt}  |  ETA {eta_txt}")
        root.update_idletasks()

    # ---- 이벤트 ----
    def browse_dir():
        d = filedialog.askdirectory()
        if d:
            out_var.set(d)

    def fetch_qualities():
        # 단일 URL 우선, 없으면 멀티의 첫 줄
        target_url = url_var.get().strip()
        if not target_url:
            lines = [ln.strip() for ln in urls_text.get("1.0", tk.END).splitlines() if ln.strip()]
            if lines:
                target_url = lines[0]
        if not target_url:
            messagebox.showwarning("확인", "URL을-입력하거나-멀티라인에-붙여넣으세요")
            return
        try:
            log("가용-품질-조회-중...\n")
            heights, info = fetch_available_heights(
                target_url,
                proxy=proxy_var.get().strip() or None,
                cookies=Path(cookie_var.get().strip()) if cookie_var.get().strip() else None
            )
            nonlocal available_heights
            available_heights = heights
            pick_heights_into_combo(heights)
            log(f"가능-해상도: {', '.join([str(h)+'p' for h in heights])}\n")
            dump_format_table(info, log)
        except Exception as e:
            messagebox.showerror("오류", f"가용-품질-조회-실패: {e}")

    def load_txt_list():
        f = filedialog.askopenfilename(
            title="TXT-파일-선택",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if not f:
            return
        try:
            with open(f, "r", encoding="utf-8") as fp:
                lines = [ln.strip() for ln in fp.readlines()]
            urls_text.delete("1.0", tk.END)
            urls_text.insert(tk.END, "\n".join([ln for ln in lines if ln]))
            messagebox.showinfo("완료", f"총-{len([ln for ln in lines if ln])}-개의-URL-불러옴")
        except Exception as e:
            messagebox.showerror("오류", f"불러오기-실패: {e}")

    def help_proxy_cookies():
        msg = (
            "프록시·쿠키 도움말\n\n"
            "프록시(proxy):\n"
            "- 회사망/지역제한/속도 이슈 대응용. 예) http://127.0.0.1:8080 또는 socks5://127.0.0.1:1080\n\n"
            "쿠키 파일(cookies.txt):\n"
            "- 로그인 필요/연령제한/멤버십 영상 접근용. 브라우저에서 cookies.txt(넷스케이프 형식)로 내보낸 뒤 지정.\n"
        )
        messagebox.showinfo("도움말-프록시/쿠키", msg)

    def collect_urls():
        single = url_var.get().strip()
        multi = [ln.strip() for ln in urls_text.get("1.0", tk.END).splitlines() if ln.strip()]
        urls = []
        if single:
            urls.append(single)
        urls.extend(multi)
        seen, final = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                final.append(u)
        return final

    def start_download_batch():
        urls = collect_urls()
        if not urls:
            messagebox.showwarning("확인", "URL을-입력하거나-멀티라인/TXT-리스트를-사용하세요")
            return

        outdir = Path(out_var.get().strip() or "downloads")

        # 가용 해상도 조회 안 했으면 '최고'만 허용
        height_choice = res_combo.get().strip() if res_combo["state"] == "readonly" else "최고"
        audio_only = audio_var.get()
        container_choice = cont_combo.get() or "auto"

        fmt_expr = build_format_expr(height_choice, audio_only)

        # UI 초기화
        txt.configure(state="normal"); txt.delete("1.0", tk.END); txt.configure(state="disabled")
        pb["value"] = 0
        prog_label_var.set("대기-중...")

        total_files = len(urls)
        current_index = {"i": 0}

        def on_progress_wrapper(percent, speed, eta, total, done):
            on_progress(percent, speed, eta, total, done)
            overall = (current_index["i"] + percent/100.0) / max(1, total_files) * 100
            overall_pb["value"] = max(0.0, min(100.0, overall))

        def worker():
            errors = 0
            for idx, u in enumerate(urls, 1):
                current_index["i"] = idx - 1
                log(f"\n=== [{idx}/{total_files}] 시작: {u}\n")
                try:
                    info, outfile, w, h, fps, codec, size_mb = download(
                        url=u,
                        outdir=outdir,
                        format_expr=fmt_expr,
                        container_choice=container_choice,
                        subtitle=(not nosub_var.get()),
                        subtitle_langs=sublang_var.get().strip(),
                        thumb=thumb_var.get(),
                        rate_limit=rate_var.get().strip() or None,
                        retries=int(retry_var.get()),
                        proxy=proxy_var.get().strip() or None,
                        cookies=Path(cookie_var.get().strip()) if cookie_var.get().strip() else None,
                        on_progress=on_progress_wrapper,
                        on_log=log
                    )
                    title = (info.get("title") if isinstance(info, dict) else None) or (outfile.name if outfile else "파일")
                    quality_str = ""
                    if w and h:
                        quality_str += f"{w}x{h}"
                    if fps:
                        quality_str += f" | {fps:.2f}fps"
                    if codec:
                        quality_str += f" | {codec}"
                    if size_mb:
                        quality_str += f" | {size_mb:.1f}MB"
                    if not quality_str:
                        quality_str = "실제-정보-확인-불가"
                    log(f"완료: {title}  →  {quality_str}\n")
                except Exception as e:
                    errors += 1
                    log(f"오류: {u}  →  {e}\n")

            messagebox.showinfo("완료", f"일괄-다운로드-완료-총-{total_files}-개-오류-{errors}-개")
            overall_pb["value"] = 100

        threading.Thread(target=worker, daemon=True).start()

    # ---- 레이아웃 ----
    row = 0
    tk.Label(root, text="단일-URL").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    url_var = tk.StringVar()
    tk.Entry(root, textvariable=url_var, width=74).grid(row=row, column=1, columnspan=3, sticky="we", padx=6, pady=6)

    row += 1
    tk.Label(root, text="여러-URL(한줄-하나)").grid(row=row, column=0, sticky="ne", padx=6, pady=6)
    urls_text = tk.Text(root, height=5)
    urls_text.grid(row=row, column=1, columnspan=2, sticky="we", padx=6, pady=6)
    tk.Button(root, text="TXT-불러오기", command=load_txt_list).grid(row=row, column=3, padx=6, pady=6, sticky="n")

    row += 1
    tk.Label(root, text="저장폴더").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    out_var = tk.StringVar(value=str(Path("downloads").absolute()))
    tk.Entry(root, textvariable=out_var, width=56).grid(row=row, column=1, sticky="we", padx=6, pady=6)
    tk.Button(root, text="찾기", command=browse_dir).grid(row=row, column=2, padx=6, pady=6)
    tk.Button(root, text="가용-품질-조회", command=fetch_qualities).grid(row=row, column=3, padx=6, pady=6)

    row += 1
    tk.Label(root, text="컨테이너").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    from tkinter import ttk
    cont_combo = ttk.Combobox(root, values=["auto", "mp4", "mkv"], state="readonly", width=10)
    cont_combo.set("auto")
    cont_combo.grid(row=row, column=1, sticky="w", padx=6, pady=6)

    tk.Label(root, text="해상도").grid(row=row, column=2, sticky="e", padx=6, pady=6)
    res_combo = ttk.Combobox(root, state="disabled", width=14)  # 초기엔 비활성화
    res_combo["values"] = ["(가용-품질-조회-필요)"]
    res_combo.set("(가용-품질-조회-필요)")
    res_combo.grid(row=row, column=3, sticky="w", padx=6, pady=6)

    row += 1
    audio_var = tk.BooleanVar(value=False)
    nosub_var = tk.BooleanVar(value=False)
    thumb_var = tk.BooleanVar(value=False)
    tk.Checkbutton(root, text="오디오-만", variable=audio_var).grid(row=row, column=1, sticky="w", padx=6)
    tk.Checkbutton(root, text="자막-없음", variable=nosub_var).grid(row=row, column=2, sticky="w", padx=6)
    tk.Checkbutton(root, text="썸네일", variable=thumb_var).grid(row=row, column=3, sticky="w", padx=6)

    row += 1
    tk.Label(root, text="자막언어").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    sublang_var = tk.StringVar(value="ko,en")
    tk.Entry(root, textvariable=sublang_var, width=18).grid(row=row, column=1, sticky="w", padx=6, pady=6)

    tk.Label(root, text="속도제한").grid(row=row, column=2, sticky="e", padx=6, pady=6)
    rate_var = tk.StringVar()
    tk.Entry(root, textvariable=rate_var, width=12).grid(row=row, column=3, sticky="w", padx=6, pady=6)

    row += 1
    tk.Label(root, text="프록시").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    proxy_var = tk.StringVar()
    tk.Entry(root, textvariable=proxy_var, width=28).grid(row=row, column=1, sticky="w", padx=6, pady=6)

    tk.Label(root, text="재시도").grid(row=row, column=2, sticky="e", padx=6, pady=6)
    retry_var = tk.StringVar(value="10")
    tk.Entry(root, textvariable=retry_var, width=8).grid(row=row, column=3, sticky="w", padx=6, pady=6)

    row += 1
    tk.Label(root, text="쿠키-파일").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    cookie_var = tk.StringVar()
    tk.Entry(root, textvariable=cookie_var, width=28).grid(row=row, column=1, sticky="w", padx=6, pady=6)
    tk.Button(root, text="프록시·쿠키-도움말", command=help_proxy_cookies).grid(row=row, column=2, columnspan=2, padx=6, pady=6, sticky="w")

    row += 1
    tk.Button(root, text="일괄-다운로드-시작", command=start_download_batch).grid(row=row, column=0, columnspan=4, pady=8)

    row += 1
    from tkinter import ttk as _ttk
    pb = _ttk.Progressbar(root, orient="horizontal", mode="determinate", length=940, maximum=100)
    pb.grid(row=row, column=0, columnspan=4, sticky="we", padx=6, pady=(4, 0))

    row += 1
    prog_label_var = tk.StringVar(value="대기-중...")
    tk.Label(root, textvariable=prog_label_var, anchor="w").grid(row=row, column=0, columnspan=4, sticky="we", padx=6)

    row += 1
    tk.Label(root, text="전체-진행률").grid(row=row, column=0, sticky="e", padx=6, pady=6)
    overall_pb = _ttk.Progressbar(root, orient="horizontal", mode="determinate", length=940, maximum=100)
    overall_pb.grid(row=row, column=1, columnspan=3, sticky="we", padx=6, pady=(4, 0))

    row += 1
    txt = tk.Text(root, height=12, state="disabled")
    txt.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=6, pady=6)
    root.grid_rowconfigure(row, weight=1)
    root.grid_columnconfigure(1, weight=1)

    root.mainloop()

# ---------- 엔트리포인트 ----------
def main():
    run_gui()

if __name__ == "__main__":
    main()
