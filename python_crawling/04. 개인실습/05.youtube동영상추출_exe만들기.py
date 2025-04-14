import os
import sys
import yt_dlp
import shutil
import subprocess
import re
import json
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

#############################################
# 0. 실행 파일 내 리소스(base_path) 설정
#############################################
# PyInstaller로 패키징된 경우 sys._MEIPASS를 사용
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

#############################################
# 1. ffmpeg 경로 설정 (내장 ffmpeg 폴더 사용)
#############################################
# 실행 파일과 함께 배포할 ffmpeg의 상대 경로 (예: ffmpeg\bin)
ffmpeg_path = os.path.join(base_path, "ffmpeg", "bin")
if os.path.exists(ffmpeg_path):
    os.environ["PATH"] += os.pathsep + ffmpeg_path
else:
    print("[ERROR] ffmpeg 폴더를 찾을 수 없습니다. ffmpeg 폴더가 포함되었는지 확인해 주세요!")
    exit(1)

#############################################
# 2. PDF 한글 폰트 등록 (NanumGothic.ttf)
#############################################
# 실행 파일과 함께 배포할 폰트 파일 (예: fonts\NanumGothic.ttf)
font_path = os.path.join(base_path, "fonts", "NanumGothic.ttf")
if not os.path.exists(font_path):
    print("[ERROR] 한글 폰트 파일을 찾을 수 없습니다. 폰트 파일이 포함되었는지 확인해 주세요!")
    exit(1)
pdfmetrics.registerFont(TTFont('NanumGothic', font_path))

#############################################
# 3. 다운로드 폴더 설정 (config.json 사용)
#############################################
CONFIG_FILE = 'config.json'

def get_download_folder():
    # 기존 설정이 있다면 config.json에서 다운로드 폴더 경로를 읽어옴
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            download_folder = config.get('download_folder', None)
            if download_folder and os.path.exists(download_folder):
                return download_folder
            else:
                print("[WARNING] 저장된 다운로드 폴더 경로가 유효하지 않습니다.")
    # 설정 파일이 없거나 유효하지 않은 경우 사용자에게 입력받음
    folder = input("다운로드 폴더의 경로를 입력하세요: ").strip()
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({'download_folder': folder}, f, ensure_ascii=False, indent=4)
    return folder

download_folder = get_download_folder()
print(f"다운로드 폴더: {download_folder}")

#############################################
# 4. 텍스트 파일(links.txt)로부터 동영상 링크 읽기 및 유효성 검사
#############################################
def get_video_links():
    links_file = 'links.txt'
    links = []
    
    if os.path.exists(links_file):
        with open(links_file, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url:  # 빈 줄 제거
                    # URL이 http:// 또는 https:// 로 시작하는지 간단히 체크
                    if re.match(r'^https?://', url):
                        links.append(url)
                    else:
                        print(f"[WARNING] 유효하지 않은 URL 형식: {url}")
        if links:
            print(f"[INFO] {len(links)}개의 유효한 링크를 '{links_file}'에서 불러왔습니다.")
        else:
            print(f"[ERROR] '{links_file}' 파일에 유효한 URL이 없습니다.")
    else:
        print(f"[ERROR] '{links_file}' 파일을 찾을 수 없습니다.")
    
    return links

#############################################
# 5. 동영상 형식 및 자막 확인 함수
#############################################
def list_formats_and_subtitles(video_url):
    try:
        with yt_dlp.YoutubeDL({'skip_download': True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
            print("\n🖼️ [INFO] ▶️ 사용 가능한 영상 형식:")
            for fmt in info['formats']:
                res = fmt.get('resolution', 'Unknown')
                size = fmt.get('filesize', 'Unknown')
                ext = fmt.get('ext', 'N/A')
                print(f"  🎞️ ID: {fmt['format_id']}, 해상도: {res}, 크기: {size} bytes, 형식: {ext}")
            subtitles = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})
            print("\n🔤 [INFO] ▶️ 사용자 제공 자막 언어:")
            for lang, tracks in subtitles.items():
                print(f"  🌐 {lang}: {tracks}")
            print("\n⚙️ [INFO] ▶️ 자동 생성 자막 언어:")
            for lang, tracks in auto_subs.items():
                print(f"  🤖 {lang}: {tracks}")
            if not subtitles and not auto_subs:
                print("⚠️ [WARNING] ▶️ 자막이 없는 영상입니다! (영상은 자막 없이 다운로드됨)")
            return bool(subtitles or auto_subs)
    except Exception as e:
        print(f"❌ [ERROR] ▶️ 형식 및 자막 코드 조회 실패: {e}")
        return False

#############################################
# 6. 동영상 다운로드 (자막 포함) 함수
#############################################
def download_video_with_subtitles(video_url):
    try:
        with yt_dlp.YoutubeDL({'skip_download': True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
            video_title = info.get('title', 'unknown_video')
            safe_title = re.sub(r'[\/:*?"<>|]', '_', video_title.replace(' ', '_'))[:50]
        
        video_folder = os.path.join(download_folder, safe_title)
        os.makedirs(video_folder, exist_ok=True)
        subtitle_folder = os.path.join(video_folder, "subtitles")
        os.makedirs(subtitle_folder, exist_ok=True)
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'outtmpl': f'{video_folder}/{safe_title}.%(ext)s',
            'ffmpeg_location': ffmpeg_path,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'ko'],
            'subtitlesformat': 'vtt',
            'embedsubs': True,
            'keepvideo': True,
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegEmbedSubtitle'}
            ],
            'noplaylist': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            print(f"\n✅ [INFO] ▶️ 다운로드 완료: {safe_title} (한국어 & 영어 자막 포함)")
        return safe_title
    except Exception as e:
        print(f"❌ [ERROR] ▶️ 다운로드 실패: {video_url}, 오류: {e}")
        return None

#############################################
# 7. 자막 파일 백업 및 PDF/TXT 생성 함수
#############################################
def backup_subtitles_and_generate_files(video_title):
    src_folder = os.path.join(download_folder, video_title)
    dest_folder = os.path.join(src_folder, "subtitles")
    os.makedirs(dest_folder, exist_ok=True)
    
    subtitle_files = [f"{video_title}.ko.vtt", f"{video_title}.en.vtt"]
    backed_up = False
    
    for file in subtitle_files:
        src_path = os.path.join(src_folder, file)
        dest_path = os.path.join(dest_folder, file)
        if os.path.exists(src_path):
            shutil.copy2(src_path, dest_path)
            print(f"🗂️ [INFO] ▶️ 자막 파일 별도 보관 완료: {dest_path}")
            backed_up = True
            
            # TXT 파일 생성
            txt_path = os.path.join(dest_folder, f"{file}.txt")
            with open(src_path, 'r', encoding='utf-8') as f:
                content = f.read()
            content = re.sub(r'<[^>]+>', '', content)  # 태그 제거
            content = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}\n', '', content)  # 시간 제거
            content = re.sub(r'\n+', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()
            
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"📄 [INFO] ▶️ TXT 파일 생성 완료: {txt_path}")
            
            # PDF 파일 생성
            pdf_path = os.path.join(dest_folder, f"{file}.pdf")
            doc = SimpleDocTemplate(pdf_path, pagesize=A4)
            story = []
            style = getSampleStyleSheet()["BodyText"]
            style.fontName = 'NanumGothic'
            for line in content.split('. '):
                if line.strip():
                    story.append(Paragraph(line.strip(), style))
            doc.build(story)
            print(f"📄 [INFO] ▶️ PDF 파일 생성 완료: {pdf_path}")
    
    if not backed_up:
        print("⚠️ [WARNING] ▶️ 자막 파일을 찾을 수 없습니다. 자막이 영상에만 포함되었을 수 있습니다.")

#############################################
# 8. 다운로드된 자막 파일 위치 출력 함수
#############################################
def print_subtitle_location(video_title):
    subtitle_folder = os.path.join(download_folder, video_title, "subtitles")
    subtitle_files = [
        os.path.join(subtitle_folder, f"{video_title}.ko.vtt"),
        os.path.join(subtitle_folder, f"{video_title}.en.vtt")
    ]
    print("\n🗂️ [INFO] ▶️ 별도로 저장된 자막 파일:")
    for file in subtitle_files:
        if os.path.exists(file):
            print(f"  ✅ {os.path.abspath(file)}")
        else:
            print(f"  ⚠️ {file} 파일이 없습니다")

#############################################
# 9. 임시 파일 정리 함수
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
            print(f"🧹 [INFO] ▶️ 불필요한 파일 삭제: {temp_file}")

#############################################
# 10. 메인 실행: 링크 파일에서 URL 읽고 순차적으로 처리
#############################################
if __name__ == "__main__":
    # links.txt 파일에서 다운로드할 동영상 URL들을 읽어옴
    video_urls = get_video_links()
    if not video_urls:
        print("[ERROR] 다운로드할 URL이 없으므로 프로그램을 종료합니다.")
        exit(1)
    
    for url in video_urls:
        has_subtitles = list_formats_and_subtitles(url)
        if has_subtitles:
            video_title = download_video_with_subtitles(url)
            if video_title:
                backup_subtitles_and_generate_files(video_title)
                print_subtitle_location(video_title)
                clean_temp_files(video_title)
        else:
            print("[INFO] 자막이 없는 영상이므로 다운로드를 건너뜁니다.")
