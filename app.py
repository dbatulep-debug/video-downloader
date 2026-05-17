import sys
import os
import subprocess
import requests
import yt_dlp
import re
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap, QGuiApplication

# MAC APP PATH FIX: Ensuring app can find FFmpeg
os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin" + os.pathsep + "/usr/local/bin"
FFMPEG_PATH = "/opt/homebrew/bin"

# UTILITY FUNCTION TO CONVERT MM:SS to SECONDS
def time_to_sec(t_str):
    try:
        if not t_str: return 0
        parts = list(map(int, t_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: return parts[0]*60 + parts[1]
        return int(parts[0])
    except: return 0

# ================= PREVIEW THREAD =================
class PreviewThread(QThread):
    preview_ready = Signal(str, bytes)
    preview_error = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(self.url, download=False)
                title = info.get("title", "Unknown Title")
                thumb_url = info.get("thumbnail", "")
                
                img_data = b""
                if thumb_url:
                    img_data = requests.get(thumb_url).content
                
                self.preview_ready.emit(title, img_data)
        except Exception:
            self.preview_error.emit("Failed to load preview")

# ================= DOWNLOAD THREAD =================
class Downloader(QThread):
    progress_signal = Signal(int)
    status_signal = Signal(str)
    convert_signal = Signal(int, str)

    def __init__(self, url, folder, quality, is_mp3, file_format, advanced_cfg):
        super().__init__()
        self.url = url
        self.folder = folder
        self.quality = quality
        self.is_mp3 = is_mp3
        self.file_format = file_format
        self.cfg = advanced_cfg  # Dictionary for advanced settings

    def run(self):
        def hook(d):
            if d['status'] == 'downloading':
                try:
                    if 'total_bytes' in d and d['total_bytes'] > 0:
                        percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                        self.progress_signal.emit(int(percent))
                    elif 'total_bytes_estimate' in d and d['total_bytes_estimate'] > 0:
                        percent = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                        self.progress_signal.emit(int(percent))
                except Exception:
                    pass
            elif d['status'] == 'finished':
                self.progress_signal.emit(100)

        try:
            self.status_signal.emit("⏳ Downloading Best Quality...")
            
            ydl_opts = {
                'outtmpl': f"{self.folder}/%(title)s_raw.%(ext)s",
                'ffmpeg_location': FFMPEG_PATH,
                'progress_hooks': [hook]
            }

            if self.is_mp3:
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'outtmpl': f"{self.folder}/%(title)s.%(ext)s",
                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
                })
            else:
                quality_map = {
                    "720p": "bestvideo[height<=720]+bestaudio/best",
                    "1080p": "bestvideo[height<=1080]+bestaudio/best",
                    "4K": "bestvideo+bestaudio/best"
                }
                ydl_opts.update({
                    'format': quality_map[self.quality],
                    'merge_output_format': self.file_format,
                })

            # --- SMART CLIPPER LOGIC ---
            if self.cfg.get('use_clipper'):
                s_time = time_to_sec(self.cfg.get('start_time', '0'))
                e_time = time_to_sec(self.cfg.get('end_time', '0'))
                if e_time > s_time:
                    ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(s_time, e_time)])
                    self.status_signal.emit(f"✂️ Clipping from {s_time}s to {e_time}s...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                raw_file = ydl.prepare_filename(info)
                duration = info.get("duration", 0)

            # AUTO PREMIERE FIX + ADVANCED SETTINGS LOGIC
            if not self.is_mp3:
                self.status_signal.emit("🛠️ Optimizing Video...")
                final_output = raw_file.replace("_raw", "")
                
                # Metadata Cleaner setup
                meta_cmd = ["-map_metadata", "-1"] if self.cfg.get('clean_meta') else []
                
                cmd = [f"{FFMPEG_PATH}/ffmpeg", "-i", raw_file, "-c:v", "libx264", "-crf", "18", 
                       "-preset", "fast", "-c:a", "aac", "-b:a", "320k", "-y"] + meta_cmd + [final_output]
                
                process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
                time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
                
                for line in process.stderr:
                    match = time_regex.search(line)
                    if match:
                        h, m, s = match.groups()
                        current_sec = int(h) * 3600 + int(m) * 60 + float(s)
                        if duration > 0:
                            pct = min(100, int((current_sec / duration) * 100))
                            self.convert_signal.emit(pct, f"Time: {int(current_sec)}s / {duration}s ({pct}%)")
                        else:
                            self.convert_signal.emit(0, f"Converted: {int(current_sec)}s")
                            
                process.wait()
                
                # Auto-Splitter Logic (Basic 60s cut)
                if self.cfg.get('auto_split'):
                    self.status_signal.emit("✂️ Splitting into 60s Shorts...")
                    split_base = final_output.replace(f".{self.file_format}", "_Part%03d.mp4")
                    split_cmd = [
                        f"{FFMPEG_PATH}/ffmpeg", "-i", final_output, "-c", "copy", "-map", "0", 
                        "-segment_time", "60", "-f", "segment", "-reset_timestamps", "1", split_base
                    ]
                    subprocess.run(split_cmd, check=True)
                
                if os.path.exists(raw_file):
                    os.remove(raw_file)
                
                self.status_signal.emit("✅ Download & Optimization Done!")
                self.convert_signal.emit(100, "Completed!")
            else:
                self.status_signal.emit("✅ MP3 Download Complete!")

        except Exception as e:
            self.status_signal.emit(f"❌ Error: {str(e)}")

# ================= ADVANCED SETTINGS DIALOG =================
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Advanced Settings")
        self.setFixedSize(320, 240)
        self.setStyleSheet("background-color: #1e1e1e; color: white; font-family: 'Segoe UI';")
        layout = QVBoxLayout()
        
        # 1. Clipper Option with Time Inputs
        self.cb_clipper = QCheckBox("✂️ Enable Smart Clipper (Time Stamps)")
        
        time_box = QHBoxLayout()
        self.start_t = QLineEdit()
        self.start_t.setPlaceholderText("Start MM:SS")
        self.end_t = QLineEdit()
        self.end_t.setPlaceholderText("End MM:SS")
        
        time_box.addWidget(QLabel("From:"))
        time_box.addWidget(self.start_t)
        time_box.addWidget(QLabel("To:"))
        time_box.addWidget(self.end_t)
        
        # Disable text boxes by default unless checked
        self.start_t.setEnabled(False)
        self.end_t.setEnabled(False)
        self.cb_clipper.toggled.connect(self.start_t.setEnabled)
        self.cb_clipper.toggled.connect(self.end_t.setEnabled)
        
        # 2. Other Features
        self.cb_split = QCheckBox("✂️ Auto-Splitter (60s Shorts)")
        self.cb_meta = QCheckBox("🛡️ Anti-Copyright (Clear Metadata)")
        
        layout.addWidget(self.cb_clipper)
        layout.addLayout(time_box)
        layout.addWidget(self.cb_split)
        layout.addWidget(self.cb_meta)
        
        btn = QPushButton("Save & Close")
        btn.setStyleSheet("background-color: #ff4b4b; padding: 8px; border-radius: 4px; font-weight: bold;")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        
        self.setLayout(layout)

# ================= MAIN UI =================
class YTDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⚡ YT Downloader Pro")
        self.setFixedSize(500, 700)
        
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #ffffff; font-family: 'Segoe UI', Arial; }
            QLineEdit, QComboBox { background-color: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 8px; color: #fff; }
            QPushButton { background-color: #ff4b4b; color: white; font-weight: bold; padding: 12px; border-radius: 8px; border: none; }
            QPushButton:hover { background-color: #ff3333; }
            QPushButton#secondary { background-color: #2b2b2b; border: 1px solid #444; }
            QProgressBar { border: none; background-color: #1e1e1e; height: 8px; border-radius: 4px; text-align: center; color: transparent; }
            QProgressBar::chunk { background-color: #ff4b4b; border-radius: 4px; }
            QLabel#title_label { font-size: 15px; font-weight: bold; color: #ffffff; }
        """)

        self.settings_dlg = SettingsDialog(self)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # TOP BAR: AUTO PASTE & SETTINGS
        top_bar = QHBoxLayout()
        self.auto_paste_cb = QCheckBox("📋 Auto-Paste URL")
        self.auto_paste_cb.setChecked(True)
        top_bar.addWidget(self.auto_paste_cb)
        
        top_bar.addStretch()
        
        btn_set = QPushButton("⚙️ Settings")
        btn_set.setFixedWidth(100)
        btn_set.setObjectName("secondary")
        btn_set.clicked.connect(self.settings_dlg.exec)
        top_bar.addWidget(btn_set)
        layout.addLayout(top_bar)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste URL here (Auto Preview)...")
        self.url_input.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url_input)

        self.thumbnail = QLabel("Thumbnail Preview")
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background-color: #1e1e1e; border-radius: 10px;")
        self.thumbnail.setFixedSize(460, 220)
        layout.addWidget(self.thumbnail)

        self.title_label = QLabel("Waiting for link...")
        self.title_label.setObjectName("title_label")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        h_layout = QHBoxLayout()
        self.quality = QComboBox()
        self.quality.addItems(["1080p", "720p", "4K"])
        h_layout.addWidget(self.quality)

        self.format = QComboBox()
        self.format.addItems(["MP4 (Standard)", "MKV (Best Quality)"])
        h_layout.addWidget(self.format)
        layout.addLayout(h_layout)

        folder_layout = QHBoxLayout()
        self.folder = QLineEdit(os.path.expanduser("~/Downloads"))
        self.folder.setReadOnly(True)
        folder_layout.addWidget(self.folder)

        self.folder_btn = QPushButton("Folder")
        self.folder_btn.setFixedWidth(80)
        self.folder_btn.setObjectName("secondary")
        self.folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_btn)
        layout.addLayout(folder_layout)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        status_layout = QHBoxLayout()
        self.status = QLabel("Ready.")
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_layout.addWidget(self.status)

        self.convert_label = QLabel("")
        self.convert_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.convert_label.setStyleSheet("color: #ffaa00; font-weight: bold; font-size: 12px;")
        status_layout.addWidget(self.convert_label)

        layout.addLayout(status_layout)

        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("🎥 Download Video")
        self.download_btn.clicked.connect(self.start_video_download)
        btn_layout.addWidget(self.download_btn)

        self.mp3_btn = QPushButton("🎵 Download MP3")
        self.mp3_btn.setObjectName("secondary")
        self.mp3_btn.clicked.connect(self.start_mp3_download)
        btn_layout.addWidget(self.mp3_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.start_preview_thread)
        
        self.preview_thread = None
        self.download_thread = None

        # CONNECT CLIPBOARD FOR AUTO-PASTE
        QGuiApplication.clipboard().dataChanged.connect(self.check_clipboard)

    def check_clipboard(self):
        if self.auto_paste_cb.isChecked():
            text = QGuiApplication.clipboard().text()
            if "http" in text and self.url_input.text() != text:
                self.url_input.setText(text)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder: self.folder.setText(folder)

    def on_url_changed(self, text):
        if "http" in text:
            self.status.setText("🔍 Fetching preview...")
            self.preview_timer.start(800) 
        else:
            self.thumbnail.clear()
            self.title_label.setText("Waiting for link...")
            self.convert_label.setText("")

    def start_preview_thread(self):
        url = self.url_input.text()
        if not url: return
        self.preview_thread = PreviewThread(url)
        self.preview_thread.preview_ready.connect(self.on_preview_ready)
        self.preview_thread.preview_error.connect(self.status.setText)
        self.preview_thread.start()

    def on_preview_ready(self, title, img_data):
        self.title_label.setText(title)
        if img_data:
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)
            self.thumbnail.setPixmap(pixmap.scaled(460, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText("✅ Preview Loaded!")

    def get_advanced_cfg(self):
        return {
            'auto_split': self.settings_dlg.cb_split.isChecked(),
            'clean_meta': self.settings_dlg.cb_meta.isChecked(),
            'use_clipper': self.settings_dlg.cb_clipper.isChecked(),
            'start_time': self.settings_dlg.start_t.text(),
            'end_time': self.settings_dlg.end_t.text()
        }

    def start_video_download(self):
        url = self.url_input.text()
        if not url: return
        self.progress.setValue(0)
        self.convert_label.setText("")
        file_ext = "mkv" if "MKV" in self.format.currentText() else "mp4"
        cfg = self.get_advanced_cfg()
        self.download_thread = Downloader(url, self.folder.text(), self.quality.currentText(), False, file_ext, cfg)
        self.download_thread.progress_signal.connect(self.progress.setValue)
        self.download_thread.status_signal.connect(self.status.setText)
        self.download_thread.convert_signal.connect(self.update_convert_ui)
        self.download_thread.start()

    def start_mp3_download(self):
        url = self.url_input.text()
        if not url: return
        self.progress.setValue(0)
        self.convert_label.setText("")
        cfg = self.get_advanced_cfg()
        self.download_thread = Downloader(url, self.folder.text(), "720p", True, "mp3", cfg)
        self.download_thread.progress_signal.connect(self.progress.setValue)
        self.download_thread.status_signal.connect(self.status.setText)
        self.download_thread.convert_signal.connect(self.update_convert_ui)
        self.download_thread.start()

    def update_convert_ui(self, pct, text_str):
        self.progress.setValue(pct)
        self.convert_label.setText(f"⚙️ {text_str}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YTDownloader()
    window.show()
    sys.exit(app.exec())
