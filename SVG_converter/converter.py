# 자동 지정 실행 파일 생성
import os
import cv2
import numpy as np
import svgwrite
import subprocess
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import json

CONFIG_FILE = "converter_config.json"

def load_config():
    """설정 파일이 있으면 불러와서 dict로 반환, 없으면 기본값 반환"""
    default_config = {
        "input_folder": r"C:\python_Study\SVG_converter\input",
        "output_folder": r"output",
        "inkscape_path": r"C:\Program Files\Inkscape\bin\inkscape.exe"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 누락된 값이 있을 경우 기본값으로 채움
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            return config
        except Exception as e:
            print("설정 파일 로드 실패:", e)
    return default_config

def save_config(config):
    """config dict를 JSON 파일에 저장"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("설정 파일 저장 실패:", e)

def quantize_image(image, k=6):
    """
    k-means를 이용하여 이미지의 색상을 k개로 양자화합니다.
    """
    Z = image.reshape((-1, 3))
    Z = np.float32(Z)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    ret, label, center = cv2.kmeans(Z, k, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
    center = np.uint8(center)
    quantized = center[label.flatten()]
    quantized = quantized.reshape(image.shape)
    return quantized, center, label.reshape((image.shape[0], image.shape[1]))

def vectorize_quantized_image(image, quantized, centers, label_matrix, svg_path):
    """
    양자화된 이미지에서 각 색상 영역의 컨투어를 검출해 개별 폴리곤으로 SVG 파일에 저장합니다.
    """
    height, width, _ = image.shape
    dwg = svgwrite.Drawing(svg_path, size=(f"{width}px", f"{height}px"))
    
    for i, color in enumerate(centers):
        mask = (label_matrix == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hex_color = '#%02x%02x%02x' % (int(color[2]), int(color[1]), int(color[0]))
        for cnt in contours:
            if len(cnt) > 2:
                epsilon = 0.001 * cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, epsilon, True)
                points = [(int(pt[0][0]), int(pt[0][1])) for pt in approx]
                dwg.add(dwg.polygon(points, fill=hex_color, stroke=hex_color))
    dwg.save()
    print(f"SVG 벡터화 파일 생성: {svg_path}")

def convert_svg_to_emf(inkscape_path, svg_path, emf_path):
    """
    Inkscape를 사용하여 SVG 파일(svg_path)을 EMF 파일(emf_path)로 변환합니다.
    """
    cmd = [
        inkscape_path,
        svg_path,
        '--export-filename=' + emf_path
    ]
    subprocess.run(cmd, check=True)

def process_files(input_folder, output_folder, inkscape_path, log_callback):
    """
    인풋 폴더 내의 모든 파일을 처리하여 output 폴더에 SVG 및 EMF 파일을 생성합니다.
    기존 파일이 있어도 덮어쓰기 합니다.
    """
    os.makedirs(output_folder, exist_ok=True)
    for filename in os.listdir(input_folder):
        input_file = os.path.join(input_folder, filename)
        if not os.path.isfile(input_file):
            continue
        ext = os.path.splitext(filename)[1].lower()
        base_name = os.path.splitext(filename)[0]
        output_svg_file = os.path.join(output_folder, base_name + ".svg")
        output_emf_file = os.path.join(output_folder, base_name + ".emf")
        log_callback(f"처리 중: {filename}\n")
        try:
            if ext == ".svg":
                shutil.copyfile(input_file, output_svg_file)
                log_callback(f"SVG 파일 복사: {output_svg_file}\n")
                convert_svg_to_emf(inkscape_path, output_svg_file, output_emf_file)
                log_callback(f"EMF 파일 생성: {output_emf_file}\n")
            elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']:
                img = cv2.imread(input_file)
                if img is None:
                    log_callback(f"이미지 로드 실패: {input_file}\n")
                    continue
                quantized, centers, label_matrix = quantize_image(img, k=6)
                vectorize_quantized_image(img, quantized, centers, label_matrix, output_svg_file)
                log_callback(f"SVG 벡터화 파일 생성: {output_svg_file}\n")
                convert_svg_to_emf(inkscape_path, output_svg_file, output_emf_file)
                log_callback(f"EMF 파일 생성: {output_emf_file}\n")
            else:
                log_callback(f"지원하지 않는 파일 형식: {ext}\n")
        except Exception as e:
            log_callback(f"오류 발생: {e}\n")
    log_callback("모든 파일 처리 완료!\n")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SVG to EMF Converter")
        self.geometry("600x450")
        self.create_widgets()
        self.load_config()

    def create_widgets(self):
        # Input folder selection
        tk.Label(self, text="Input Folder:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.input_folder_var = tk.StringVar()
        self.input_entry = tk.Entry(self, textvariable=self.input_folder_var, width=50)
        self.input_entry.grid(row=0, column=1, padx=5, pady=5)
        tk.Button(self, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=5, pady=5)
        
        # Output folder selection
        tk.Label(self, text="Output Folder:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.output_folder_var = tk.StringVar()
        self.output_entry = tk.Entry(self, textvariable=self.output_folder_var, width=50)
        self.output_entry.grid(row=1, column=1, padx=5, pady=5)
        tk.Button(self, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=5, pady=5)
        
        # Inkscape path selection
        tk.Label(self, text="Inkscape Path:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.inkscape_var = tk.StringVar()
        self.inkscape_entry = tk.Entry(self, textvariable=self.inkscape_var, width=50)
        self.inkscape_entry.grid(row=2, column=1, padx=5, pady=5)
        tk.Button(self, text="Browse", command=self.browse_inkscape).grid(row=2, column=2, padx=5, pady=5)
        
        # Run button
        self.run_button = tk.Button(self, text="Run", command=self.run_conversion)
        self.run_button.grid(row=3, column=1, pady=10)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(self, width=70, height=15)
        self.log_text.grid(row=4, column=0, columnspan=3, padx=5, pady=5)
    
    def browse_input(self):
        folder = filedialog.askdirectory(title="Select Input Folder")
        if folder:
            self.input_folder_var.set(folder)
    
    def browse_output(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder_var.set(folder)
    
    def browse_inkscape(self):
        file = filedialog.askopenfilename(title="Select Inkscape Executable", filetypes=[("Executable Files", "*.exe")])
        if file:
            self.inkscape_var.set(file)
    
    def log_callback(self, message):
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
    
    def run_conversion(self):
        input_folder = self.input_folder_var.get()
        output_folder = self.output_folder_var.get()
        inkscape_path = self.inkscape_var.get()
        
        if not input_folder or not output_folder or not inkscape_path:
            messagebox.showerror("Error", "모든 경로를 지정하세요!")
            return
        
        self.run_button.config(state=tk.DISABLED)
        thread = threading.Thread(target=process_files, args=(input_folder, output_folder, inkscape_path, self.log_callback))
        thread.start()
        self.after(100, lambda: self.check_thread(thread))
    
    def check_thread(self, thread):
        if thread.is_alive():
            self.after(100, lambda: self.check_thread(thread))
        else:
            self.run_button.config(state=tk.NORMAL)
            messagebox.showinfo("완료", "모든 파일 처리 완료되었습니다.")
            self.save_config()
    
    def load_config(self):
        config = load_config()
        self.input_folder_var.set(config.get("input_folder", ""))
        self.output_folder_var.set(config.get("output_folder", ""))
        self.inkscape_var.set(config.get("inkscape_path", ""))
    
    def save_config(self):
        config = {
            "input_folder": self.input_folder_var.get(),
            "output_folder": self.output_folder_var.get(),
            "inkscape_path": self.inkscape_var.get()
        }
        save_config(config)
    
    def on_closing(self):
        self.save_config()
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
