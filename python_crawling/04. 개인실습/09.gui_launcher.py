import tkinter as tk
from tkinter import messagebox
import requests
import platform
import subprocess
import os
import json

# Google Apps Script 웹앱 URL
SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxTXJ85qSiYryn0KGoJK8KXn5IIEBXRI9X-YOgo43okUoOmfd3g0DFQA_lqwLadGXGT/exec"

# ✅ PC 이름 가져오기 (줄바꿈, 공백, 대소문자 모두 정리)
def get_pc_name():
    return platform.node().strip().replace("\r", "").replace("\n", "").lower()

# 사용자 정보 저장
def save_user_info(name, email):
    with open("user_info.json", "w") as f:
        json.dump({"name": name, "email": email}, f)

# 사용자 정보 불러오기
def load_user_info():
    if os.path.exists("user_info.json"):
        with open("user_info.json", "r") as f:
            return json.load(f)
    return None

# ✅ 승인 여부 확인 (email/pc 정제)
def check_approval(email, pc):
    try:
        res = requests.get(SCRIPT_URL, params={
            "email": email.strip().lower(),
            "pc": pc.strip().lower()
        }, timeout=5)
        result = res.json()
        return result.get("approved", False)
    except Exception as e:
        messagebox.showerror("오류", f"승인 확인 실패\n{str(e)}")
        return False

# ✅ 가입 신청 요청 (중복 방지 위해 정제)
def apply_for_access(name, email, pc):
    try:
        response = requests.post(SCRIPT_URL, data={
            "name": name.strip(),
            "email": email.strip().lower(),
            "pc": pc.strip().lower()
        }, timeout=5)

        if response.status_code == 200:
            print("가입 신청 성공:", response.text)
            return True
        else:
            print("가입 신청 실패:", response.text)
            return False

    except Exception as e:
        messagebox.showerror("오류", f"가입 신청 실패\n{str(e)}")
        return False

# ✅ 이렇게 수정 (정확하게 log=true를 POST data로 넘기기)
def log_execution(name, email, pc):
    try:
        requests.post(SCRIPT_URL, data={
            "log": "true",
            "name": name,
            "email": email,
            "pc": pc
        }, timeout=5)
    except Exception as e:
        print(f"[WARNING] 실행 로그 전송 실패: {e}")

# 버튼 클릭 처리
def on_submit():
    name = name_entry.get().strip()
    email = email_entry.get().strip()
    pc = get_pc_name()

    if not name or not email:
        messagebox.showwarning("입력 필요", "이름과 이메일을 입력해주세요.")
        return

    save_user_info(name, email)

    if check_approval(email, pc):
        log_execution(name, email, pc)
        messagebox.showinfo("인증 성공", "승인이 완료되었습니다. 프로그램을 실행합니다.")
        root.destroy()
        run_main_program()
    else:
        if apply_for_access(name, email, pc):
            messagebox.showinfo("신청 완료", "가입 신청이 완료되었습니다.\n승인 후 다시 실행해주세요.")
        root.destroy()

# 본 프로그램 실행 (예: 동영상 다운로더)
def run_main_program():
    subprocess.call([
        "c:/python_Study/plot/Scripts/python.exe",  # 사용자 환경에 맞게 경로 수정
        "08.youtube동영상추출_exe만들기_보안_v5.py"
    ])

# === GUI 구성 ===
root = tk.Tk()
root.title("프로그램 인증")
root.geometry("300x200")

tk.Label(root, text="이름").pack(pady=(10, 0))
name_entry = tk.Entry(root)
name_entry.pack()

tk.Label(root, text="이메일").pack(pady=(10, 0))
email_entry = tk.Entry(root)
email_entry.pack()

tk.Button(root, text="가입 신청 / 실행", command=on_submit).pack(pady=20)

# 자동 정보 불러오기
info = load_user_info()
if info:
    name_entry.insert(0, info.get("name", ""))
    email_entry.insert(0, info.get("email", ""))

root.mainloop()
