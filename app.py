import streamlit as st
import yt_dlp
import os
import subprocess
import cv2

# ================= APP CONFIGURATION =================
st.set_page_config(page_title="Pro Downloader AI", page_icon="👑", layout="wide")

# FFMPEG is pre-installed on Streamlit Cloud via packages.txt
FFMPEG_LOC = "ffmpeg"

def time_to_sec(t_str):
    try:
        parts = list(map(int, t_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: return parts[0]*60 + parts[1]
        return parts[0]
    except: return 0

# ================= UI LAYOUT =================
st.title("👑 Pro Downloader AI v6.3 (Web Edition)")
st.markdown("---")

# Top Configuration Bar
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    preset = st.selectbox("Quality Preset:", [
        "🎬 Premiere Pro - 4K (Fast)", 
        "🎬 Premiere Pro - 1080p (Fast)", 
        "📱 Instagram Reels (MP4)", 
        "🎵 Audio MP3"
    ])
with col2:
    split_ratio = st.selectbox("Crop / Split Mode:", [
        "Original (16:9)", 
        "Vertical 9:16 (Center)",
        "🤖 AI Face Tracking (Vertical 9:16) ⚡",
        "Vertical 9:16 (Blur Background) 🔥",
        "Square 1:1 (Center)"
    ])
with col3:
    st.write("Advanced Options:")
    clean_meta = st.checkbox("🛡️ Anti-Copyright")

# Tabs for different download modes
tab1, tab2 = st.tabs(["🎯 Single Download", "🎬 Bulk Download"])

with tab1:
    single_url = st.text_input("🔗 Paste a single link here...", placeholder="https://...")
    
    st.write("✂️ Smart Clipper (Optional):")
    clip_col1, clip_col2 = st.columns(2)
    with clip_col1:
        t_start = st.text_input("Start Time (MM:SS)", placeholder="00:00")
    with clip_col2:
        t_end = st.text_input("End Time (MM:SS)", placeholder="00:00")

with tab2:
    bulk_urls_text = st.text_area("🔗 Paste multiple video links here (One per line)...", height=150)

# ================= PROCESSING ENGINE =================
if st.button("🚀 START PROCESS", use_container_width=True, type="primary"):
    urls = []
    if single_url:
        urls.append(single_url)
    elif bulk_urls_text:
        urls = [u.strip() for u in bulk_urls_text.split('\n') if u.strip()]
    
    if not urls:
        st.warning("⚠️ Please provide at least one URL.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_box = st.empty()
        
        logs = []
        def update_log(msg):
            logs.append(msg)
            log_box.code("\n".join(logs), language="bash")

        media_type = 'Audio' if 'Audio' in preset else 'Video'
        
        # Base yt-dlp options
        ydl_opts = {
            'ffmpeg_location': FFMPEG_LOC,
            'quiet': True,
            'outtmpl': 'downloaded_temp_raw.%(ext)s',
            'merge_output_format': 'mkv'
        }

        if media_type == 'Audio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            })
        else:
            ydl_opts.update({'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'})

        # Smart Clipper Logic
        if t_start and t_end:
            start_s = time_to_sec(t_start)
            end_s = time_to_sec(t_end)
            if end_s > start_s:
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(start_s, end_s)])
                update_log(f"✂️ Smart Clipper Active: {start_s}s to {end_s}s")

        for idx, url in enumerate(urls, 1):
            status_text.success(f"Processing ({idx}/{len(urls)})...")
            update_log(f"🚀 Initializing Download for Link {idx}...")
            
            try:
                # Cleanup previous temp files
                for f in os.listdir("."):
                    if f.startswith("downloaded_temp"):
                        os.remove(f)

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get('title', f'video_{idx}')
                    actual_ext = "mp3" if media_type == "Audio" else "mp4"
                    
                downloaded_file = f"downloaded_temp_raw.{actual_ext}"
                final_file = f"Final_{title}.{actual_ext}".replace("/", "_").replace('"', '')

                update_log(f"✅ Download Complete. Starting Optimization...")

                # Optimization & Metadata Cleaning
                if media_type == "Video":
                    meta_cmd = ["-map_metadata", "-1"] if clean_meta else []
                    ffmpeg_cmd = [FFMPEG_LOC, "-i", downloaded_file, "-c:v", "copy", "-c:a", "copy", "-y"] + meta_cmd + [final_file]
                    subprocess.run(ffmpeg_cmd, check=True)
                    update_log(f"✅ Optimization & Metadata rules applied.")
                else:
                    os.rename(downloaded_file, final_file)

                # Provide Download Button to the User
                with open(final_file, "rb") as file_data:
                    st.download_button(
                        label=f"⬇️ Download {title}",
                        data=file_data,
                        file_name=final_file,
                        mime=f"video/mp4" if media_type == "Video" else "audio/mpeg"
                    )
                
                progress_bar.progress(int((idx / len(urls)) * 100))
                
            except Exception as e:
                update_log(f"❌ Error on Link {idx}: {str(e)}")

        status_text.success("🎯 All Tasks Completed! Files are ready for download.")
