import streamlit as st
import os
import time
import re
import shutil
import tempfile
from dotenv import load_dotenv
from google import genai
from moviepy.editor import VideoFileClip, concatenate_videoclips

load_dotenv()

API_KEY = os.getenv("API_KEY")

# ========== NEW LOGIC: SPLIT + PROCESS ON THE FLY ==========

def generate_and_process_clips(input_path):
    """
    Generates 1-minute clips *temporarily*, uploads to Gemini, processes,
    and deletes the temp file immediately.
    """
    client = genai.Client(api_key=API_KEY)
    video = VideoFileClip(input_path)
    duration = int(video.duration)
    chunk_length = 60

    responses = []

    for idx, start in enumerate(range(0, duration, chunk_length), start=1):
        end = min(start + chunk_length, duration)

        # --- Create temp file for this clip ---
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            temp_path = tmp.name

        # --- Write the clip to a temporary file ---
        subclip = video.subclip(start, end)
        subclip.write_videofile(
            temp_path,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=f"temp_audio_{idx}.m4a",
            remove_temp=True,
            verbose=False,
            logger=None
        )

        # --- Upload to Gemini ---
        myfile = client.files.upload(file=temp_path)

        # Wait until ACTIVE or FAILED
        while True:
            myfile = client.files.get(name=myfile.name)
            if myfile.state in ("ACTIVE", "FAILED"):
                break
            time.sleep(3)

        # --- Prompt ---
        prompt = """
        Tell me the timestamp of a team scoring, be sure that the net moves. It might happen that there is no goal, or more than 1. Return only the list of timestamps
        of goals, something like this: [00:00:12, 00:00:29, ...], in case there is no goal then [].
        IMPORTANT: don't output any other character apart from the list.
        """

        # --- Call Gemini model ---
        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash", contents=[myfile, prompt]
                )
                break
            except:
                time.sleep(2)

        if response is None:
            output_text = "[]"
        else:
            output_text = response.text.strip()

        responses.append({
            "clip_number": idx,
            "file_id": myfile.name,
            "response": output_text
        })

        # --- DELETE the temporary clip file ---
        if os.path.exists(temp_path):
            os.remove(temp_path)

    video.close()
    return responses

# ========== THE REST OF YOUR ORIGINAL FUNCTIONS (unchanged) ==========

def process_responses(responses):
    def time_to_sec(t):
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s

    def sec_to_time(sec):
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    final_times = []
    for i, entry in enumerate(responses):
        offset = i * 60
        timestamps = re.findall(r"\d{2}:\d{2}:\d{2}", entry["response"])
        for t in timestamps:
            final_times.append(sec_to_time(time_to_sec(t) + offset))

    return final_times


def extract_highlights_merged(video_path, timestamps, pre=10, post=10):
    def t_to_sec(t):
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s

    raw_intervals = []
    for t in timestamps:
        c = t_to_sec(t)
        raw_intervals.append((c - pre, c + post))

    raw_intervals.sort()
    merged = []
    for s, e in raw_intervals:
        if not merged:
            merged.append([s, e])
        else:
            last_s, last_e = merged[-1]
            if s <= last_e:
                merged[-1][1] = max(last_e, e)
            else:
                merged.append([s, e])

    video = VideoFileClip(video_path)
    clips = []
    for s, e in merged:
        s = max(0, s)
        e = min(video.duration, e)
        clips.append(video.subclip(s, e))

    final = concatenate_videoclips(clips)
    output_path = "final_highlights.mp4"
    final.write_videofile(output_path, codec="libx264", audio_codec="aac")
    video.close()
    return output_path

# ========== STREAMLIT APP ==========

def main():
    st.title("Match Highlighter")

    if "forza_inter" not in st.session_state:
        st.session_state.forza_inter = False

    if not st.session_state.forza_inter:
        if st.button("💙🖤 FORZA INTER 🖤💙 (ti voglio bene ale)"):
            st.session_state.forza_inter = True
        else:
            st.info("Premi il pulsante *Forza Inter* per iniziare!")
            return

    uploaded = st.file_uploader("Carica il video della partita", type=["mp4", "mov"])

    if uploaded:
        input_path = "input_video.mp4"
        with open(input_path, "wb") as f:
            f.write(uploaded.read())

        st.video(input_path)

        if st.button("Inizia Elaborazione"):
            st.write("### Analisi dei gol con Gemini...")
            responses = generate_and_process_clips(input_path)

            st.write("### Unione dei timestamp dei tiri...")
            timestamps = process_responses(responses)

            st.write("Orari dei tiri rilevati:", timestamps)

            if timestamps:
                st.write("### Creazione video highlights...")
                output_video = extract_highlights_merged(input_path, timestamps)

                st.video(output_video)

                with open(output_video, "rb") as f:
                    st.download_button(
                        label="⬇️ Scarica Highlights",
                        data=f,
                        file_name="highlights.mp4",
                        mime="video/mp4"
                    )
            else:
                st.warning("Nessun gol rilevato.")

if __name__=='__main__':
    main()
