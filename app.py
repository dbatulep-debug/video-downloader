import streamlit as st
import yt_dlp
import os
import subprocess
import requests
import imageio_ffmpeg  # Internal FFmpeg loader

# ================= APP CONFIGURATION =================
st.set_page_config(page_title="YT Downloader Pro", page_icon="⚡", layout="centered")

# AUTOMATIC INTERNAL FFMPEG DETECTION
try:
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_PATH = "ffmpeg"

# UTILITY FUNCTION TO CONVERT MM:SS to SECONDS
def time_to_sec(t_str):
    try:
        if not t_str: return 0
        parts = list(map(int, t_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: return parts[0]*60 + parts[1]
        return int(parts[0])
    except: return 0

# ================= MAIN UI DISPLAY =================
st.title("⚡ YT Downloader Pro (Web Edition)")
st.write("---")

st.caption("📋 Ready to paste video link below")

with st.expander("⚙️ Advanced Settings"):
    cb_clipper = st.checkbox("✂️ Enable Smart Clipper (Time Stamps)")
    time_col1, time_col2 = st.columns(2)
    with time_col1:
        start_t = st.text_input("Start Time (MM:SS)", placeholder="00:00", disabled=not cb_clipper)
    with time_col2:
        end_t = st.text_input("End Time (MM:SS)", placeholder="00:00", disabled=not cb_clipper)
        
    cb_split = st.checkbox("✂️ Auto-Splitter (60s Shorts)")
    cb_meta = st.checkbox("🛡️ Anti-Copyright (Clear Metadata)")

# URL Input Field
url_input = st.text_input("Paste URL here (Auto Preview)...", placeholder="https://...")

# --- AUTO PREVIEW ENGINE ---
if url_input and "http" in url_input:
    try:
        preview_opts = {
            'quiet': True,
            'cookiefile': 'cookies.txt',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        with yt_dlp.YoutubeDL(preview_opts) as ydl:
            info = ydl.extract_info(url_input, download=False)
            title = info.get("title", "Unknown Title")
            thumb_url = info.get("thumbnail", "")
            
            st.write(f"**🎬 Title:** {title}")
            if thumb_url:
                st.image(thumb_url, use_container_width=True)
    except:
        st.caption("🔍 Loading preview... You can proceed to process.")

# Quality and Format Selectors
h_col1, h_col2 = st.columns(2)
with h_col1:
    quality = st.selectbox("Select Quality:", ["1080p", "720p", "4K"])
with h_col2:
    format_sel = st.selectbox("Select Format:", ["MP4 (Standard)", "MKV (Best Quality)"])

file_format = "mkv" if "MKV" in format_sel else "mp4"

st.write("---")

# Action Buttons
btn_col1, btn_col2 = st.columns(2)
video_click = False
audio_click = False

with btn_col1:
    if st.button("🎥 Download Video", use_container_width=True, type="primary"):
        video_click = True
with btn_col2:
    if st.button("🎵 Download MP3", use_container_width=True):
        audio_click = True

# ================= PROCESSING ENGINE =================
if video_click or audio_click:
    if not url_input:
        st.warning("⚠️ Please paste a valid video URL first!")
    else:
        status = st.empty()
        progress = st.progress(0)
        is_mp3 = audio_click
        
        # Housekeeping: Clear older files to save cloud space
        for f in os.listdir("."):
            if f.startswith("downloaded_") or f.startswith("Final_") or f.endswith(".mp4") or f.endswith(".mkv") or f.endswith(".mp3"):
                try: os.remove(f)
                except: pass

        # SMART FLEXIBLE FORMAT SELECTION ENGINE
        ydl_opts = {
            'ffmpeg_location': FFMPEG_PATH,
            'quiet': True,
            'outtmpl': 'downloaded_raw.%(ext)s',
            'cookiefile': 'cookies.txt',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                    'skip': ['dash', 'hls']
                }
            }
        }

        if is_mp3:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': 'downloaded_raw.%(ext)s',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            })
        else:
            # Flexible format matching your dynamic resolution engine
            if quality == "720p":
                ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best'
            elif quality == "1080p":
                ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best'
            else: # 4K
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            
            # Let yt-dlp merge it natively first, then we process it cleanly
            ydl_opts['merge_output_format'] = 'mkv'

        # Clipper parameters logic
        if cb_clipper and start_t and end_t:
            s_time = time_to_sec(start_t)
            e_time = time_to_sec(end_t)
            if e_time > s_time:
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(s_time, e_time)])
                status.info(f"✂️ Clipping from {s_time}s to {e_time}s...")

        try:
            status.warning("⏳ Fetching Streams and Downloading from Server...")
            progress.progress(25)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_input, download=True)
                title_clean = info.get('title', 'video').replace("/", "_").replace('"', '').replace("'", "")
            
            progress.progress(60)
            
            if is_mp3:
                status.success("✅ MP3 Processing Done!")
                final_file = f"Final_{title_clean}.mp3"
                if os.path.exists("downloaded_raw.mp3"):
                    os.rename("downloaded_raw.mp3", final_file)
                
                with open(final_file, "rb") as f:
                    st.download_button("⬇️ Save MP3 to Device", data=f, file_name=final_file, mime="audio/mpeg")
            else:
                status.warning("🛠️ Processing and Converting to Target Format...")
                
                # Check what format yt-dlp generated natively
                raw_file = "downloaded_raw.mkv"
                if not os.path.exists(raw_file):
                    if os.path.exists("downloaded_raw.mp4"):
                        raw_file = "downloaded_raw.mp4"
                    elif os.path.exists("downloaded_raw.webm"):
                        raw_file = "downloaded_raw.webm"
                
                final_output = f"Final_{title_clean}.{file_format}"
                meta_cmd = ["-map_metadata", "-1"] if cb_meta else []
                
                # Dynamic re-encoding to ensure perfect standard mp4/mkv compatibility
                cmd = [FFMPEG_PATH, "-i", raw_file, "-c:v", "libx264", "-crf", "18", 
                       "-preset", "fast", "-c:a", "aac", "-b:a", "320k", "-y"] + meta_cmd + [final_output]
                subprocess.run(cmd, check=True)
                
                progress.progress(85)
                
                if cb_split:
                    status.warning("✂️ Splitting into 60s Shorts...")
                    split_base = f"Final_{title_clean}_Part%03d.mp4"
                    split_cmd = [FFMPEG_PATH, "-i", final_output, "-c", "copy", "-map", "0", 
                                 "-segment_time", "60", "-f", "segment", "-reset_timestamps", "1", split_base]
                    subprocess.run(split_cmd, check=True)
                    
                    status.success("✅ Segments generated successfully:")
                    import glob
                    parts = sorted(glob.glob(f"Final_{title_clean}_Part*.mp4"))
                    for part in parts:
                        with open(part, "rb") as f:
                            st.download_button(f"⬇️ Download {os.path.basename(part)}", data=f, file_name=os.path.basename(part), mime="video/mp4")
                else:
                    status.success("✅ Video Processing Complete!")
                    with open(final_output, "rb") as f:
                        st.download_button("⬇️ Save Video to Device", data=f, file_name=final_output, mime=f"video/{file_format}")
                        
            progress.progress(100)
            
        except Exception as e:
            status.error(f"❌ System Error: {str(e)}")
