# 무작위 User-Agent 헤더를 적용, 아이피 차단 위험 방지 코드 추가, 라이브러리 업데이트 (V3에서 )
import os, sys, re, json, threading, queue, time, subprocess, random
import yt_dlp, shutil
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from time import gmtime, strftime

#############################################
# 자동 라이브러리 업데이트 함수 (#1)
#############################################
def update_libraries():
    libraries = ['yt-dlp', 'pytube']  # 필요에 따라 추가 가능
    for lib in libraries:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", lib])
        except Exception as e:
            print(f"[WARNING] {lib} 업데이트 실패: {e}")

# 프로그램 시작 시 라이브러리 업데이트 시도
update_libraries()

#############################################
# 사용자 에이전트 목록 (랜덤 선택)
#############################################
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    # 추가적인 사용자 에이전트 문자열을 필요에 따라 추가
]

#############################################
# 0. 실행 파일 내 리소스(base_path) 설정
#############################################
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

#############################################
# 1. ffmpeg 경로 설정 (내장 ffmpeg 폴더 사용)
#############################################
ffmpeg_path = os.path.join(base_path, "ffmpeg", "bin")
if os.path.exists(ffmpeg_path):
    os.environ["PATH"] += os.pathsep + ffmpeg_path
else:
    print("[ERROR] ffmpeg 폴더를 찾을 수 없습니다. ffmpeg 폴더가 포함되었는지 확인해 주세요!")
    exit(1)

#############################################
# 2. PDF 한글 폰트 등록 (NanumGothic.ttf)
#############################################
font_path = os.path.join(base_path, "fonts", "NanumGothic.ttf")
if not os.path.exists(font_path):
    print("[ERROR] 한글 폰트 파일을 찾을 수 없습니다. 폰트 파일이 포함되었는지 확인해 주세요!")
    exit(1)
pdfmetrics.registerFont(TTFont('NanumGothic', font_path))

#############################################
# 3. 다운로드 폴더 설정 (config.json 사용)
#############################################
CONFIG_FILE = 'config.json'
download_folder = None  # 전역 변수
stop_flag = False       # 다운로드 중지 플래그

def get_download_folder():
    global download_folder
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            folder = config.get('download_folder', None)
            if folder and os.path.exists(folder):
                download_folder = folder
                return folder
            else:
                print("[WARNING] 저장된 다운로드 폴더 경로가 유효하지 않습니다.")
    folder = filedialog.askdirectory(title="다운로드 폴더 선택")
    if folder:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'download_folder': folder}, f, ensure_ascii=False, indent=4)
        download_folder = folder
        return folder
    else:
        messagebox.showerror("오류", "다운로드 폴더를 선택해야 합니다.")
        exit(1)

#############################################
# 3-1. 프록시 설정 함수 (#2)
#############################################
def get_proxy():
    # config.json에 proxy 값이 있으면 사용 (예: "http://proxy.example.com:8080")
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            proxy = config.get('proxy', '')
            return proxy.strip()
    return ''

#############################################
# 4. URL 목록 관리: 파일에서 URL 불러오기 기능
#############################################
def load_urls_from_file():
    urls = []
    links_file = 'links.txt'
    if os.path.exists(links_file):
        with open(links_file, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url and re.match(r'^https?://', url):
                    urls.append(url)
    return urls

#############################################
# 5. 동영상 형식 및 자막 확인 함수
#############################################
def list_formats_and_subtitles(video_url):
    try:
        with yt_dlp.YoutubeDL({'skip_download': True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
            subtitles = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})
            return bool(subtitles or auto_subs)
    except Exception as e:
        print(f"[ERROR] 자막 정보 조회 실패: {e}")
        return False

#############################################
# 6. ANSI 코드 제거 함수
#############################################
def remove_ansi_codes(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

#############################################
# 7. ETA 형식 변환 함수
#############################################
def parse_yt_dlp_time(t_str: str) -> str:
    """
    '3m00.2s', '0:37', '1h2m3s' 등 다양한 형태를 HH:MM:SS로 변환.
    """
    t_str = remove_ansi_codes(t_str).strip().lower()
    pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?'
    m = re.match(pattern, t_str)
    if not m:
        if re.match(r'^\d+:\d+$', t_str):
            parts = t_str.split(':')
            mm = int(parts[0])
            ss = int(parts[1])
            return f"00:{mm:02d}:{ss:02d}"
        return "00:00:00"
    hours = m.group(1) or '0'
    minutes = m.group(2) or '0'
    seconds = m.group(3) or '0'
    total_seconds = int(hours)*3600 + int(minutes)*60 + float(seconds)
    h = int(total_seconds // 3600)
    m_ = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    return f"{h:02d}:{m_:02d}:{s:02d}"

#############################################
# 8. 약어 보호/복원 함수
#############################################
ABBREVIATIONS = [
    'Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Sr.', 'Jr.', 'etc.',
    'St.', 'vs.', 'i.e.'
]

def protect_abbrev(text: str) -> str:
    for abbr in ABBREVIATIONS:
        pattern = re.escape(abbr)
        text = re.sub('(?i)'+pattern, abbr.replace('.', '§'), text)
    return text

def restore_abbrev(text: str) -> str:
    return text.replace('§', '.')

#############################################
# 9. VTT 파일에서 완전한 문장 추출 (cue 블록 단위)
#############################################
def process_vtt_file(src_path):
    with open(src_path, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = re.split(r'\n\s*\n', content)
    final_lines = []
    for block in blocks:
        lines = block.splitlines()
        if not any(re.match(r'^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->', line) for line in lines):
            continue
        text_lines = [line for line in lines if not re.match(r'^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->', line)]
        cleaned_lines = []
        for line in text_lines:
            line = re.sub(r'<[^>]+>', '', line)
            line = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', line)
            line = line.strip()
            if line:
                cleaned_lines.append(line)
        if not cleaned_lines:
            continue
        chosen_line = None
        for line in cleaned_lines:
            if not re.search(r'\d{2}:\d{2}:\d{2}\.\d{3}', line):
                chosen_line = line
                break
        if not chosen_line:
            chosen_line = max(cleaned_lines, key=len)
        final_lines.append(chosen_line)
    dedup_lines = []
    prev = None
    for line in final_lines:
        if line != prev:
            dedup_lines.append(line)
        prev = line
    return "\n".join(dedup_lines)

#############################################
# 10. 동영상 다운로드 (자막 포함) 함수
#############################################
def download_video_with_subtitles(video_url, progress_hook):
    global download_folder, stop_flag
    try:
        stop_flag = False  # 다운로드 시작 시 중지 플래그 초기화
        
        # 사용자 에이전트를 무작위로 선택
        headers = {"User-Agent": random.choice(user_agents)}
        proxy = get_proxy()

        # 정보를 미리 받아오기 (프록시 및 http_headers 옵션 추가)
        ydl_opts_info = {
            'skip_download': True,
            'quiet': False,
            'noprogress': False,
            'http_headers': headers
        }
        if proxy:
            ydl_opts_info['proxy'] = proxy
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_title = info.get('title', 'unknown_video')
            safe_title = re.sub(r'[\/:*?"<>|]', '_', video_title.replace(' ', '_'))[:50]
        
        video_folder = os.path.join(download_folder, safe_title)
        os.makedirs(video_folder, exist_ok=True)
        subtitle_folder = os.path.join(video_folder, "subtitles")
        os.makedirs(subtitle_folder, exist_ok=True)
        
        # 다운로드 옵션에 무작위 사용자 에이전트 적용
        ydl_opts = {
            'quiet': False,
            'noprogress': False,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'outtmpl': f'{video_folder}/{safe_title}.%(ext)s',
            'ffmpeg_location': ffmpeg_path,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'ko'],
            'subtitlesformat': 'vtt',
            'embedsubs': True,
            'keepvideo': True,
            'progress_hooks': [progress_hook],
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegEmbedSubtitle'}
            ],
            'noplaylist': True,
            'http_headers': {"User-Agent": random.choice(user_agents)}
        }
        if proxy:
            ydl_opts['proxy'] = proxy
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return safe_title
    except Exception as e:
        print(f"[ERROR] 다운로드 실패: {video_url}, {e}")
        return None

#############################################
# 11. 자막 파일 백업 및 PDF/TXT 생성 함수
#############################################
def backup_subtitles_and_generate_files(video_title):
    src_folder = os.path.join(download_folder, video_title)
    dest_folder = os.path.join(src_folder, "subtitles")
    os.makedirs(dest_folder, exist_ok=True)
    subtitle_candidates = [
        f"{video_title}.ko.vtt",
        f"{video_title}.ko.[auto].vtt",
        f"{video_title}.en.vtt",
        f"{video_title}.en.[auto].vtt"
    ]
    for file in subtitle_candidates:
        src_path = os.path.join(src_folder, file)
        if not os.path.exists(src_path):
            continue
        dest_path = os.path.join(dest_folder, file)
        shutil.copy2(src_path, dest_path)
        txt_path = os.path.join(dest_folder, f"{file}.txt")
        pdf_path = os.path.join(dest_folder, f"{file}.pdf")
        
        raw_text = process_vtt_file(src_path)
        one_line_text = " ".join(raw_text.splitlines())
        protected_text = protect_abbrev(one_line_text)
        sentences = re.split(r'(?<=[.?!])\s+', protected_text, flags=re.IGNORECASE)
        sentences = [restore_abbrev(s.strip()) for s in sentences if s.strip()]
        final_text = "\n".join(sentences)
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(final_text)
        
        # PDF 생성 (기본 스타일 사용)
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        story = []
        style = getSampleStyleSheet()["BodyText"]
        style.fontName = 'NanumGothic'
        for sentence in sentences:
            story.append(Paragraph(sentence, style))
        doc.build(story)

#############################################
# 12. 다운로드된 자막 파일 위치 출력 함수
#############################################
def print_subtitle_location(video_title):
    subtitle_folder = os.path.join(download_folder, video_title, "subtitles")
    subtitle_files = [
        os.path.join(subtitle_folder, f"{video_title}.ko.vtt"),
        os.path.join(subtitle_folder, f"{video_title}.en.vtt")
    ]
    for file in subtitle_files:
        if os.path.exists(file):
            print(f"저장된 자막 파일: {os.path.abspath(file)}")

#############################################
# 13. 임시 파일 정리 함수
#############################################
def clean_temp_files(video_title):
    video_folder = os.path.join(download_folder, video_title)
    temp_files = [
        os.path.join(video_folder, f"{video_title}.f140"),
        os.path.join(video_folder, f"{video_title}.f616")
    ]
    for temp_file in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)

#############################################
# 14. GUI 클래스
#############################################
class DownloaderGUI:
    def __init__(self, master):
        self.master = master
        master.title("YouTube 동영상 다운로더")
        master.geometry("900x650")
        style = ttk.Style()
        style.theme_use('clam')
        
        # 메뉴바
        menubar = tk.Menu(master)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="종료", command=master.quit)
        menubar.add_cascade(label="파일", menu=filemenu)
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="도움말", menu=helpmenu)
        master.config(menu=menubar)
        
        # 상단 프레임: 다운로드 폴더 표시 및 변경 버튼
        top_frame = tk.Frame(master)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        self.folder_label = tk.Label(top_frame, text="다운로드 폴더: " + get_download_folder(), anchor='w')
        self.folder_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.change_folder_btn = tk.Button(top_frame, text="폴더 변경", command=self.change_folder)
        self.change_folder_btn.pack(side=tk.RIGHT)
        
        # 중앙 프레임: 좌측 URL 리스트, 우측 진행률 및 로그 영역
        center_frame = tk.Frame(master)
        center_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 좌측: URL 목록 및 관리
        left_frame = tk.Frame(center_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(left_frame, text="다운로드 URL 목록:").pack(anchor='w')
        self.listbox = tk.Listbox(left_frame, width=50, height=15, selectmode=tk.EXTENDED)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(left_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)
        
        # URL 입력 및 관리 버튼
        input_frame = tk.Frame(left_frame)
        input_frame.pack(fill=tk.X, pady=5)
        self.url_entry = tk.Entry(input_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.add_url_btn = tk.Button(input_frame, text="추가", command=self.add_url)
        self.add_url_btn.pack(side=tk.LEFT, padx=5)
        self.del_url_btn = tk.Button(input_frame, text="삭제", command=self.delete_url)
        self.del_url_btn.pack(side=tk.LEFT, padx=5)
        self.del_all_btn = tk.Button(input_frame, text="전체 삭제", command=self.delete_all_url)
        self.del_all_btn.pack(side=tk.LEFT, padx=5)
        
        self.load_url_btn = tk.Button(left_frame, text="파일에서 URL 불러오기", command=self.load_url_file)
        self.load_url_btn.pack(pady=5)
        
        # 우측: 진행률 및 로그 영역
        right_frame = tk.Frame(center_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)
        tk.Label(right_frame, text="다운로드 진행 상황:").pack(anchor='w')
        self.progress = ttk.Progressbar(right_frame, orient='horizontal', length=300, mode='determinate', maximum=100)
        self.progress.pack(pady=5)
        self.progress_label = tk.Label(right_frame, text="진행률: 0.0% , ETA : 00:00:00 → 속도: 0.00 MB/s  (URL 0/0)")
        self.progress_label.pack()
        tk.Label(right_frame, text="로그:").pack(anchor='w', pady=(10,0))
        self.log_text = tk.Text(right_frame, wrap='word', height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.clear_log_btn = tk.Button(right_frame, text="로그 지우기", command=self.clear_log)
        self.clear_log_btn.pack(pady=5)
        
        # 하단: 다운로드 시작 및 중지 버튼
        bottom_frame = tk.Frame(master)
        bottom_frame.pack(fill=tk.X, padx=10, pady=5)
        self.start_btn = tk.Button(bottom_frame, text="다운로드 시작", command=self.start_downloads)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(bottom_frame, text="다운로드 중지", command=self.stop_downloads)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        self.progress_queue = queue.Queue()
        self.master.after(100, self.update_progress)
        
        # URL 목록은 기본적으로 빈 상태
        self.video_urls = []
        self.total_urls = 0
        self.current_url_index = 0
        self.refresh_url_list()
    
    def show_about(self):
        messagebox.showinfo("About", "YouTube 동영상 다운로더\n버전 2.0\n개발자: Your Name")
    
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
    
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
    
    def refresh_url_list(self):
        self.listbox.delete(0, tk.END)
        for url in self.video_urls:
            self.listbox.insert(tk.END, url)
        self.total_urls = len(self.video_urls)
        self.current_url_index = 0
        self.update_progress_label(0.0, "00:00:00", 0.0)
    
    def change_folder(self):
        global download_folder
        new_folder = filedialog.askdirectory(title="다운로드 폴더 선택")
        if new_folder:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'download_folder': new_folder}, f, ensure_ascii=False, indent=4)
            download_folder = new_folder
            self.folder_label.config(text="다운로드 폴더: " + new_folder)
    
    def add_url(self):
        url = self.url_entry.get().strip()
        if url and re.match(r'^https?://', url):
            self.video_urls.append(url)
            self.refresh_url_list()
            self.url_entry.delete(0, tk.END)
        else:
            messagebox.showwarning("경고", "올바른 URL을 입력하세요.")
    
    def delete_url(self):
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showwarning("경고", "삭제할 URL을 선택하세요.")
            return
        for i in reversed(selected):
            del self.video_urls[i]
        self.refresh_url_list()
    
    def delete_all_url(self):
        if not self.video_urls:
            messagebox.showwarning("경고", "삭제할 URL이 없습니다.")
            return
        if messagebox.askyesno("확인", "정말 모든 URL을 삭제하시겠습니까?"):
            self.video_urls.clear()
            self.refresh_url_list()
    
    def load_url_file(self):
        file_path = filedialog.askopenfilename(title="URL 리스트 파일 선택", filetypes=[("Text Files", "*.txt")])
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url and re.match(r'^https?://', url):
                        self.video_urls.append(url)
            self.refresh_url_list()
            self.log("파일에서 URL을 불러왔습니다.\n")
    
    def start_downloads(self):
        global stop_flag
        stop_flag = False
        self.start_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.download_all, daemon=True).start()
    
    def stop_downloads(self):
        global stop_flag
        stop_flag = True
        self.log("사용자에 의해 다운로드 중지가 요청되었습니다.\n")
        messagebox.showinfo("다운로드 중지", "다운로드가 중지되었습니다.")
    
    def download_all(self):
        global stop_flag
        self.log("프로그램 실행 중...\n")
        total = len(self.video_urls)
        for i, url in enumerate(self.video_urls):
            if stop_flag:
                self.log("다운로드가 중지되었습니다.\n")
                break
            self.current_url_index = i + 1
            self.log(f"\n===== {self.current_url_index}/{total}번째 다운로드 시작 =====")
            self.log(f"URL: {url}")
            if not list_formats_and_subtitles(url):
                self.log(f"자막 없는 영상 건너뜀: {url}\n")
                continue
            
            # 수정된 progress_hook 함수: yt_dlp가 제공하는 'eta'와 'speed' 키 사용
            def progress_hook(d):
                if d['status'] == 'downloading':
                    if stop_flag:
                        raise Exception("Download stopped by user.")
                    
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    total_bytes = d.get('total_bytes', 0)
                    if total_bytes:
                        value = downloaded_bytes / total_bytes * 100
                    else:
                        percent_str = remove_ansi_codes(d.get('_percent_str', '0.0%')).strip()
                        try:
                            value = float(percent_str.replace('%','').strip())
                        except:
                            value = 0.0
                    
                    numeric_eta = d.get('eta', None)
                    if numeric_eta is not None and numeric_eta > 0:
                        eta_str = time.strftime("%H:%M:%S", time.gmtime(numeric_eta))
                    else:
                        eta_str_raw = d.get('_eta_str', '00:00:00')
                        eta_str = parse_yt_dlp_time(eta_str_raw)
                    
                    speed = d.get('speed', None)
                    if speed is not None:
                        speed_mb = speed / (1024*1024)
                    else:
                        elapsed = d.get('elapsed', 0)
                        if elapsed > 0:
                            speed_mb = (downloaded_bytes / (1024*1024)) / elapsed
                        else:
                            speed_mb = 0.0
                    
                    self.progress_queue.put((value, eta_str, speed_mb))
            
            try:
                video_title = download_video_with_subtitles(url, progress_hook)
            except Exception as e:
                err_msg = str(e)
                self.log(f"다운로드 중지/오류: {url}\n오류 내용: {err_msg}")
                messagebox.showerror("오류", f"다운로드 중 문제가 발생하였습니다: {err_msg}")
                if "403" in err_msg or "blocked" in err_msg.lower():
                    self.log("IP 차단으로 인한 오류로 보입니다. 60초 대기 후 재시도합니다.")
                    time.sleep(60)
                    continue
                break
            
            if video_title:
                backup_subtitles_and_generate_files(video_title)
                print_subtitle_location(video_title)
                clean_temp_files(video_title)
                self.log(f"다운로드 및 자막 후처리 완료: {video_title}\n")
            else:
                self.log(f"다운로드 실패: {url}\n")
            # 각 다운로드 후 2~5초 랜덤 딜레이를 추가하여 IP 차단 위험 감소
            time.sleep(random.uniform(2, 5))
        
        self.progress_queue.put((100.0, "00:00:00", 0.0))
        self.start_btn.config(state=tk.NORMAL)
        self.log("모든 다운로드가 완료되었습니다.\n")
    
    def update_progress_label(self, value, eta, speed):
        self.progress_label.config(
            text=f"진행률: {value:.1f}% , ETA : {eta} → 속도: {speed:.2f} MB/s  (URL {self.current_url_index}/{self.total_urls})"
        )
    
    def update_progress(self):
        try:
            while True:
                value, eta, speed = self.progress_queue.get_nowait()
                self.progress['value'] = value
                self.update_progress_label(value, eta, speed)
        except queue.Empty:
            pass
        self.master.after(100, self.update_progress)

#############################################
# 15. 메인 실행 (GUI)
#############################################
if __name__ == "__main__":
    root = tk.Tk()
    app = DownloaderGUI(root)
    root.mainloop()
