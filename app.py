# --- START OF app.py (Review Pref - Complete) ---

import os
import speech_recognition as sr
import moviepy.editor as mp
from flask import Flask, request, send_from_directory, jsonify, abort, url_for
from werkzeug.utils import secure_filename
from deep_translator import GoogleTranslator
import edge_tts
import asyncio
import random
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
import numpy as np
import time
from pytubefix import YouTube
from pytube import exceptions as pytube_exceptions
from pytubefix.cli import on_progress
import subprocess
import json
import math
import shutil
import traceback

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
JOBS_FOLDER = os.path.join(UPLOAD_FOLDER, 'jobs') # Still needed for review mode
os.makedirs(JOBS_FOLDER, exist_ok=True)
# Temp folder for direct processing
TEMP_DIRECT_FOLDER = os.path.join(UPLOAD_FOLDER, 'temp_direct')
os.makedirs(TEMP_DIRECT_FOLDER, exist_ok=True)


ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'mpeg', 'mpg'}
# Intermediate/Output file names/suffixes
ORIGINAL_VIDEO_FILENAME = 'original_video'
EXTRACTED_AUDIO_FILENAME = 'original_audio.wav'
CHUNK_FILENAME_PREFIX = 'chunk_'
CHUNK_AUDIO_EXTENSION = '.wav'
METADATA_FILENAME = 'metadata.json' # Used only in review mode
TTS_CHUNK_SUFFIX = '_tts.mp3'
COMBINED_TTS_FILENAME = 'combined_audio.mp3'
FINAL_VIDEO_SUFFIX = '_translated'
FINAL_VIDEO_EXTENSION = '.mp4'

# Other Settings
TARGET_LANGUAGE = 'ta'
TARGET_LOCALE = 'ta-IN'
MAX_CONTENT_LENGTH = 200 * 1024 * 1024
DEFAULT_TTS_VOICE = 'female'
MIN_SILENCE_LEN_MS = 700
SILENCE_THRESH_DBFS = -40

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['JOBS_FOLDER'] = JOBS_FOLDER
app.config['TEMP_DIRECT_FOLDER'] = TEMP_DIRECT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SECRET_KEY'] = 'replace_this_with_a_real_secret_key_too'

# --- Helper Functions (Keep ALL helpers as they were) ---
# allowed_file, extract_audio, transcribe_audio_chunk, translate_text,
# synthesize_speech_chunk, replace_video_audio, download_with_yt_dlp
# Ensure ALL these helper functions from the previous version are included here...
# (Omitted again for brevity in this response, but crucial)
# --- Placeholder for required helper functions ---
def allowed_file(filename): return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def extract_audio(video_path, output_audio_path):
    print(f"[Helper] Extracting audio from: {video_path} to {output_audio_path}")
    video_clip = None; audio_clip = None
    try:
        video_clip = mp.VideoFileClip(video_path)
        audio_clip = video_clip.audio
        if audio_clip is None: return False, "No audio track found."
        audio_clip.write_audiofile(output_audio_path, codec='pcm_s16le')
        time.sleep(0.5) # Shorter sleep?
        return True, "Audio extracted successfully."
    except Exception as e: return False, f"Extraction failed: {e}"
    finally:
        if audio_clip:
            try: audio_clip.close()
            except Exception as close_err: print(f"Warning: Error closing audio clip: {close_err}")
        if video_clip:
            try: video_clip.close()
            except Exception as close_err: print(f"Warning: Error closing video clip: {close_err}")
            
def transcribe_audio_chunk(audio_chunk_path):
    print(f"[Helper] Transcribing: {os.path.basename(audio_chunk_path)}")
    recognizer = sr.Recognizer(); text = None; message = "Transcription failed."
    try:
        if not os.path.exists(audio_chunk_path): return None, "Chunk not found."
        with sr.AudioFile(audio_chunk_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='en-US')
            message = "Transcription successful."
    except sr.UnknownValueError: message = "Audio chunk not understood."
    except sr.RequestError as e: message = f"API request failed; {e}"
    except Exception as e: message = f"Chunk transcription error: {e}"
    return text, message
def translate_text(text_to_translate):
    if not text_to_translate: return None, "No text."
    try:
        time.sleep(0.1)
        translated = GoogleTranslator(source='auto', target=TARGET_LANGUAGE).translate(text_to_translate)
        return translated or "", "Translation successful." # Return empty string if None
    except Exception as e: return None, f"Translation failed: {e}"
def synthesize_speech_chunk(text_to_speak, output_filename, voice_preference):
    if not text_to_speak: return False, "No text.", None
    target_gender = voice_preference.capitalize()
    async def find_and_synthesize_chunk_async():
        selected_voice = None; duration = None
        try:
            voices = await edge_tts.list_voices()
            matching = [v for v in voices if v['Locale'].lower() == TARGET_LOCALE.lower() and v['Gender'] == target_gender]
            if matching: selected_voice = random.choice(matching)['ShortName']
            else:
                 fallback_g = 'Male' if target_gender == 'Female' else 'Female'
                 fallback_v = [v for v in voices if v['Locale'].lower() == TARGET_LOCALE.lower() and v['Gender'] == fallback_g]
                 if fallback_v: selected_voice = random.choice(fallback_v)['ShortName']
            if not selected_voice: return False, f"No {TARGET_LOCALE} voice.", None
            communicate = edge_tts.Communicate(text_to_speak, selected_voice)
            await communicate.save(output_filename)
            if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
                 try: duration = len(AudioSegment.from_mp3(output_filename))
                 except: pass # Ignore duration error
                 return True, "OK.", duration
            else: return False, "Save failed.", None
        except Exception as e: return False, f"TTS Error: {e}", None
    try: return asyncio.run(find_and_synthesize_chunk_async())
    except RuntimeError: loop = asyncio.get_event_loop(); return loop.run_until_complete(find_and_synthesize_chunk_async())
    except Exception as e: return False, f"Async Error: {e}", None
def replace_video_audio(original_video_path, new_audio_path, output_video_path):
    print(f"[Helper] Replacing audio in {os.path.basename(original_video_path)} with {os.path.basename(new_audio_path)}")
    video_clip=None; audio_clip=None; final_video=None;
    try:
        if not os.path.exists(original_video_path): return False, "Original video missing."
        if not os.path.exists(new_audio_path): return False, "Combined audio missing."
        video_clip = mp.VideoFileClip(original_video_path)
        audio_clip = mp.AudioFileClip(new_audio_path)
        final_video = video_clip.set_audio(audio_clip)
        final_video.write_videofile(output_video_path, codec='libx264', audio_codec='aac', logger='bar')
        return True, "Video created."
    except Exception as e: return False, f"Merge failed: {e}"
    finally:
        if final_video:
             try: final_video.close()
             except Exception as close_err: print(f"Warning: Error closing final_video clip: {close_err}")
        if audio_clip:
             try: audio_clip.close()
             except Exception as close_err: print(f"Warning: Error closing audio_clip: {close_err}")
        if video_clip:
             try: video_clip.close()
             except Exception as close_err: print(f"Warning: Error closing video_clip: {close_err}")
             
def download_with_yt_dlp(url, output_path, filename):
    output_template = os.path.join(output_path, filename)
    command = ['yt-dlp','-f', 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best','--merge-output-format', 'mp4','-o', output_template,'--socket-timeout', '30',url]
    try:
        print(f"[Helper] Downloading with yt-dlp: {url}")
        process = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        return True, "Download successful."
    except subprocess.CalledProcessError as e: return False, f"yt-dlp failed: {(e.stderr or '')[:200]}..."
    except FileNotFoundError: return False, "yt-dlp not found."
    except Exception as e: return False, f"yt-dlp error: {e}"
# --- End of Placeholder ---


# --- Stage 1 Processing (FOR REVIEW MODE ONLY) ---
def process_stage1_for_review(input_path, base_filename, is_youtube):
    """Handles Stage 1 when REVIEW is selected."""
    job_id = f"{int(time.time())}_{secure_filename(base_filename)}"
    job_dir = os.path.join(app.config['JOBS_FOLDER'], job_id)
    chunks_dir = os.path.join(job_dir, 'chunks')
    os.makedirs(chunks_dir, exist_ok=True)

    original_ext = os.path.splitext(input_path)[1] if not is_youtube else '.mp4'
    original_video_target_path = os.path.join(job_dir, ORIGINAL_VIDEO_FILENAME + original_ext)
    extracted_audio_path = os.path.join(job_dir, EXTRACTED_AUDIO_FILENAME)
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)

    metadata = { 'job_id': job_id, 'base_filename': base_filename, 'original_video_path': original_video_target_path, 'chunks': [], 'status': 'Stage1Review_Processing' }
    input_path_handled = False

    try:
        # Step 0: Move/Copy input video
        try: shutil.move(input_path, original_video_target_path); input_path_handled = True
        except Exception: shutil.copy2(input_path, original_video_target_path); os.remove(input_path); input_path_handled = True
        print(f"Input video prepared in job dir: {job_id}")

        # Step 1: Extract Audio
        success, msg = extract_audio(original_video_target_path, extracted_audio_path)
        if not success or not os.path.exists(extracted_audio_path): raise ValueError(f"Audio extraction failed: {msg}")

        # Step 2: Load & Segment
        sound = AudioSegment.from_wav(extracted_audio_path)
        nonsilent_ranges = detect_nonsilent(sound, min_silence_len=MIN_SILENCE_LEN_MS, silence_thresh=SILENCE_THRESH_DBFS)
        if not nonsilent_ranges: raise ValueError("No speech detected.")
        print(f"Detected {len(nonsilent_ranges)} segments for review.")

        # Step 3 & 4: Transcribe & Translate Chunks
        last_chunk_end = 0
        for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
            silence_before = max(0, start_ms - last_chunk_end)
            chunk_audio = sound[start_ms:end_ms]
            chunk_filename = f"{CHUNK_FILENAME_PREFIX}{i}{CHUNK_AUDIO_EXTENSION}"
            chunk_path = os.path.join(chunks_dir, chunk_filename)
            try: chunk_audio.export(chunk_path, format="wav")
            except Exception as export_err: print(f"Warning: Skip chunk {i}, export failed: {export_err}"); continue

            transcribed_text, trans_msg = transcribe_audio_chunk(chunk_path)
            translated_text, translate_msg = translate_text(transcribed_text or "")

            metadata['chunks'].append({
                'index': i, 'start_ms': start_ms, 'end_ms': end_ms,
                'silence_before_ms': silence_before,
                'original_audio_chunk': chunk_filename,
                'transcribed_text': transcribed_text or "",
                'translated_text': translated_text or "",
                'transcription_status': trans_msg, 'translation_status': translate_msg
            })
            last_chunk_end = end_ms

        metadata['status'] = 'Stage1_Completed_Translation_Pending_Review'
        with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        print(f"Stage 1 (Review Mode) completed for job {job_id}")
        return True, "Ready for translation review.", metadata

    except Exception as e:
        print(f"Error during Stage 1 (Review Mode) for {job_id}: {e}")
        traceback.print_exc()
        if os.path.exists(job_dir): 
            try: shutil.rmtree(job_dir) 
            except Exception as job_dir: print(f"Warning: Error removing job_dir")
        if not input_path_handled and input_path and os.path.exists(input_path): 
            try: os.remove(input_path) 
            except Exception as input_path_err: print(f"Warning: Error removing input_path: {close_err}")
        return False, f"Processing failed during Stage 1: {str(e)}", None

# --- Final Stage Processing (AFTER REVIEW) ---
def process_final_stage_after_review(job_id, edited_translated_texts, tts_voice):
    """Handles Final Stage when REVIEW was selected."""
    job_dir = os.path.join(app.config['JOBS_FOLDER'], job_id)
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)
    chunks_dir = os.path.join(job_dir, 'chunks')
    combined_audio_path = os.path.join(job_dir, COMBINED_TTS_FILENAME)
    metadata = {}
    final_video_filename_base = "final_output"

    try:
        # Load Metadata
        if not os.path.exists(metadata_path): raise ValueError("Metadata not found.")
        with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)

        current_status = metadata.get('status')
        if current_status != 'Stage1_Completed_Translation_Pending_Review' and not current_status.startswith('FinalStage_Failed'):
             raise ValueError(f"Job {job_id} not ready for final processing (Status: {current_status})")

        metadata['status'] = 'FinalStageReview_Processing'
        try: # Save status update
             with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        except Exception: pass

        final_video_filename_base = metadata.get('base_filename', job_id)
        print(f"--- Starting Final Stage (Review Mode) for Job {job_id} ---")
        final_audio = AudioSegment.empty()
        all_tts_failed = True

        # Synthesize chunks using EDITED TRANSLATED text
        for i, chunk_meta in enumerate(metadata['chunks']):
            chunk_index = chunk_meta['index']
            silence_before = chunk_meta['silence_before_ms']
            edited_translated_text = edited_translated_texts.get(str(chunk_index))

            if silence_before > 0: final_audio += AudioSegment.silent(duration=silence_before)
            if not edited_translated_text: print(f"Chunk {chunk_index}: Skipping TTS (no edited text)."); continue

            tts_chunk_filename = f"{CHUNK_FILENAME_PREFIX}{chunk_index}{TTS_CHUNK_SUFFIX}"
            tts_chunk_path = os.path.join(chunks_dir, tts_chunk_filename)
            success, msg, duration = synthesize_speech_chunk(edited_translated_text, tts_chunk_path, tts_voice)

            if success:
                 all_tts_failed = False
                 try: final_audio += AudioSegment.from_mp3(tts_chunk_path)
                 except Exception as load_err: print(f"Warning: Failed load TTS chunk {chunk_index}: {load_err}")
            else: print(f"Warning: TTS failed chunk {chunk_index}: {msg}")

        # Export Combined Audio
        if len(final_audio) == 0:
             raise ValueError("No audio generated (All TTS failed or skipped).")
        print(f"Exporting combined audio...")
        final_audio.export(combined_audio_path, format="mp3")

        # Replace Video Audio
        original_video_path = metadata['original_video_path']
        if not os.path.exists(original_video_path): raise ValueError(f"Original video not found: {original_video_path}")
        final_video_output_filename = f"{secure_filename(final_video_filename_base)}{FINAL_VIDEO_SUFFIX}{FINAL_VIDEO_EXTENSION}"
        final_video_output_path = os.path.join(app.config['UPLOAD_FOLDER'], final_video_output_filename)
        success, msg = replace_video_audio(original_video_path, combined_audio_path, final_video_output_path)
        if not success: raise ValueError(f"Failed to create final video: {msg}")

        # Success & Cleanup
        print(f"Final Stage (Review Mode) completed. Cleaning up job directory: {job_dir}")
        try: shutil.rmtree(job_dir)
        except Exception as clean_err: print(f"Warning: Failed cleanup {job_dir}: {clean_err}")
        return True, "Video processing complete!", {'final_video_filename': final_video_output_filename}

    except Exception as e:
        print(f"Error during Final Stage (Review Mode) for job {job_id}: {e}")
        traceback.print_exc()
        metadata['status'] = f'FinalStage_Failed: {str(e)[:100]}'
        try: 
            with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        except Exception as final_stage_err: print(f"Warning: Final Stage Error")

        return False, f"Processing failed during Final Stage: {e}", None


# --- NEW: Full Pipeline Function (DIRECT MODE) ---
def run_full_pipeline_direct(input_path, base_filename, tts_voice, is_youtube):
    """Runs the full pipeline directly without review."""
    print(f"--- Starting Direct Pipeline for: {base_filename} ---")
    # Use a temporary directory within TEMP_DIRECT_FOLDER for this specific run
    run_id = f"{int(time.time())}_{secure_filename(base_filename)}"
    temp_run_dir = os.path.join(app.config['TEMP_DIRECT_FOLDER'], run_id)
    os.makedirs(temp_run_dir, exist_ok=True)

    original_ext = os.path.splitext(input_path)[1] if not is_youtube else '.mp4'
    original_video_target_path = os.path.join(temp_run_dir, ORIGINAL_VIDEO_FILENAME + original_ext)
    extracted_audio_path = os.path.join(temp_run_dir, EXTRACTED_AUDIO_FILENAME)
    combined_audio_path = os.path.join(temp_run_dir, COMBINED_TTS_FILENAME)
    # Final video saved outside temp dir
    final_video_output_filename = f"{secure_filename(base_filename)}{FINAL_VIDEO_SUFFIX}{FINAL_VIDEO_EXTENSION}"
    final_video_output_path = os.path.join(app.config['UPLOAD_FOLDER'], final_video_output_filename)

    input_path_handled = False
    all_tts_failed = True # Track if any TTS works

    try:
        # Step 0: Move/Copy input video
        try: shutil.move(input_path, original_video_target_path); input_path_handled = True
        except Exception: shutil.copy2(input_path, original_video_target_path); os.remove(input_path); input_path_handled = True
        print("Direct Mode: Input video prepared.")

        # Step 1: Extract Audio
        success, msg = extract_audio(original_video_target_path, extracted_audio_path)
        if not success or not os.path.exists(extracted_audio_path): raise ValueError(f"Audio extraction failed: {msg}")

        # Step 2: Load & Segment
        sound = AudioSegment.from_wav(extracted_audio_path)
        nonsilent_ranges = detect_nonsilent(sound, min_silence_len=MIN_SILENCE_LEN_MS, silence_thresh=SILENCE_THRESH_DBFS)
        if not nonsilent_ranges: raise ValueError("No speech detected.")
        print(f"Direct Mode: Detected {len(nonsilent_ranges)} segments.")

        # Step 3, 4, 5: Process Chunks (Transcribe, Translate, TTS) & Reconstruct Audio
        last_chunk_end = 0
        final_audio = AudioSegment.empty()

        for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
            print(f"Direct Mode: Processing chunk {i+1}...")
            silence_before = max(0, start_ms - last_chunk_end)
            chunk_audio = sound[start_ms:end_ms]
            # Use temp_run_dir for chunk files
            chunk_filename = f"{CHUNK_FILENAME_PREFIX}{i}{CHUNK_AUDIO_EXTENSION}"
            chunk_path = os.path.join(temp_run_dir, chunk_filename) # Temp chunk path
            try: chunk_audio.export(chunk_path, format="wav")
            except Exception as export_err: print(f"Warning: Skip chunk {i}, export failed: {export_err}"); continue

            transcribed_text, _ = transcribe_audio_chunk(chunk_path)
            # Use ORIGINAL translated text directly
            translated_text, _ = translate_text(transcribed_text or "")

            # Add silence before potential speech
            if silence_before > 0: final_audio += AudioSegment.silent(duration=silence_before)

            if translated_text:
                tts_chunk_filename = f"{CHUNK_FILENAME_PREFIX}{i}{TTS_CHUNK_SUFFIX}"
                tts_chunk_path = os.path.join(temp_run_dir, tts_chunk_filename) # Temp TTS path
                success, msg, duration = synthesize_speech_chunk(translated_text, tts_chunk_path, tts_voice)
                if success:
                    all_tts_failed = False
                    try: final_audio += AudioSegment.from_mp3(tts_chunk_path)
                    except Exception as load_err: print(f"Warning: Failed load TTS chunk {i}: {load_err}")
                else: print(f"Warning: TTS failed chunk {i}: {msg}")
            else: print(f"Direct Mode: Skipping TTS chunk {i} (no translated text).")

            last_chunk_end = end_ms
            try: os.remove(chunk_path) # Clean up WAV chunk immediately
            except: pass

        # Step 6: Export Combined Audio
        if len(final_audio) == 0: raise ValueError("No audio generated (All TTS likely failed/skipped).")
        final_audio.export(combined_audio_path, format="mp3")
        print("Direct Mode: Combined audio exported.")

        # Step 7: Replace Video Audio
        success, msg = replace_video_audio(original_video_target_path, combined_audio_path, final_video_output_path)
        if not success: raise ValueError(f"Failed to create final video: {msg}")

        # --- Success ---
        print(f"--- Direct Pipeline completed successfully for: {base_filename} ---")
        # Cleanup handled in finally block
        return True, "Video processing complete!", {'final_video_filename': final_video_output_filename}

    except Exception as e:
        print(f"Error during Direct Pipeline for {base_filename}: {e}")
        traceback.print_exc()
        # Cleanup handled in finally block
        return False, f"Processing failed during Direct Pipeline: {str(e)}", None

    finally:
        # --- Cleanup for Direct Mode ---
        if os.path.exists(temp_run_dir):
            print(f"Direct Mode: Cleaning up temporary run directory: {temp_run_dir}")
            try: shutil.rmtree(temp_run_dir)
            except Exception as clean_err: print(f"Warning: Failed cleanup for temp dir {temp_run_dir}: {clean_err}")
        # Ensure original input is cleaned up if move/copy failed early
        if not input_path_handled and input_path and os.path.exists(input_path):
             try: os.remove(input_path); print(f"Cleaned up original input after direct failure: {input_path}")
             except Exception as del_err: print(f"Warning: Failed cleanup original input after direct failure: {del_err}")


# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return send_from_directory(BASE_DIR, 'index.html')

# --- MODIFIED Route to initiate processing (handles both modes) ---
@app.route('/process-stage1', methods=['POST'])
def handle_process_stage1():
    """Handles initial upload/URL and starts either Direct or Review pipeline."""
    # Get preferences from form
    tts_voice = request.form.get('tts_voice', DEFAULT_TTS_VOICE)
    review_preference = request.form.get('reviewPreference', 'direct') # Default to direct

    input_path = None; base_filename = None; is_youtube = False; temp_file_to_delete = None

    try:
        # --- Handle File Upload or YouTube URL (same as before) ---
        if 'videoFile' in request.files:
            file = request.files['videoFile']
            if file.filename == '': return jsonify({"message": "No selected file"}), 400
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                base_filename = os.path.splitext(original_filename)[0]
                temp_upload_filename = f"temp_{int(time.time())}_{original_filename}"
                temp_upload_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_upload_filename)
                file.save(temp_upload_path)
                input_path = temp_upload_path
                temp_file_to_delete = input_path
            else: return jsonify({"message": "File type not allowed"}), 400
        elif 'youtube_url' in request.form:
            youtube_url = request.form['youtube_url']
            if not youtube_url: return jsonify({"message": "Missing YouTube URL"}), 400
            is_youtube = True
            base_filename_title = "youtube_video"
            timestamp = int(time.time())
            base_filename = f"{base_filename_title}_{timestamp}"
            temp_download_filename = base_filename + ".mp4"
            temp_download_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_download_filename)
            dl_success, dl_msg = download_with_yt_dlp(youtube_url, app.config['UPLOAD_FOLDER'], temp_download_filename)
            if not dl_success: raise ValueError(f"YouTube download failed: {dl_msg}")
            input_path = temp_download_path
            temp_file_to_delete = input_path
        else: return jsonify({"message": "No video input provided"}), 400

        if not input_path or not base_filename: raise ValueError("Input path/filename error.")

        # --- Decide Mode and Call Appropriate Function ---
        print(f"Processing request with review preference: {review_preference}")
        if review_preference == 'review':
            # Call Stage 1 for Review Mode
            success, message, metadata = process_stage1_for_review(input_path, base_filename, is_youtube)
            temp_file_to_delete = None # Handled by stage 1 func
            if success:
                metadata['tts_voice'] = tts_voice # Store voice choice for final stage
                job_dir = os.path.join(app.config['JOBS_FOLDER'], metadata['job_id'])
                metadata_path = os.path.join(job_dir, METADATA_FILENAME)
                try:
                    with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
                except Exception as write_err: print(f"Warning: Failed to save metadata: {write_err}")
                # Return review data for UI
                return jsonify({"message": message, "review_data": metadata, "mode": "review"}), 200
            else:
                # Stage 1 failed, cleanup handled within it
                return jsonify({"message": message}), 500
        else: # Direct Mode
            success, message, results = run_full_pipeline_direct(input_path, base_filename, tts_voice, is_youtube)
            temp_file_to_delete = None # Handled by direct func
            if success:
                 # Return final video filename directly
                 return jsonify({"message": message, **(results or {}), "mode": "direct"}), 200
            else:
                 # Direct pipeline failed, cleanup handled within it
                 return jsonify({"message": message}), 500

    except Exception as e:
        print(f"Error in /process-stage1 route: {e}")
        traceback.print_exc()
        if temp_file_to_delete and os.path.exists(temp_file_to_delete):
             print(f"Cleaning up temp file due to error in route: {temp_file_to_delete}")
             try: os.remove(temp_file_to_delete) 
             except Exception as remove_err: print(f"Warning: Error removing temp_file_to_delete")

        return jsonify({"message": f"An unexpected error occurred: {str(e)}"}), 500


@app.route('/serve-chunk/<job_id>/<chunk_filename>')
def serve_chunk(job_id, chunk_filename):
    """Serves original audio chunk files (Only needed for review mode)."""
    safe_job_id = secure_filename(job_id); safe_chunk_filename = secure_filename(chunk_filename)
    if safe_job_id != job_id or safe_chunk_filename != chunk_filename: abort(403)
    job_dir = os.path.join(app.config['JOBS_FOLDER'], safe_job_id)
    chunks_dir = os.path.join(job_dir, 'chunks')
    file_path = os.path.join(chunks_dir, safe_chunk_filename)
    if not os.path.exists(file_path) or not os.path.abspath(file_path).startswith(os.path.abspath(chunks_dir)): abort(404)
    return send_from_directory(chunks_dir, safe_chunk_filename, as_attachment=True)


@app.route('/process-final-stage', methods=['POST'])
def handle_process_final_stage():
    """Receives edited translations (Only called in review mode)."""
    data = request.get_json()
    if not data or 'job_id' not in data or 'edited_translated_texts' not in data:
         return jsonify({"message": "Missing data for final stage"}), 400

    job_id = data['job_id']; edited_translated_texts = data['edited_translated_texts']
    tts_voice = data.get('tts_voice', DEFAULT_TTS_VOICE)

    safe_job_id = secure_filename(job_id)
    if safe_job_id != job_id: return jsonify({"message": "Invalid job ID"}), 400
    job_dir = os.path.join(app.config['JOBS_FOLDER'], safe_job_id)
    if not os.path.isdir(job_dir): return jsonify({"message": "Job not found"}), 404

    # Get voice pref from metadata
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
            tts_voice = metadata.get('tts_voice', tts_voice)
        except Exception: pass

    try:
        success, message, results = process_final_stage_after_review(safe_job_id, edited_translated_texts, tts_voice)
        status_code = 200 if success else 500
        return jsonify({"message": message, **(results or {})}), status_code
    except Exception as e:
        print(f"Error in /process-final-stage route: {e}")
        traceback.print_exc()
        return jsonify({"message": f"Unexpected error during final processing: {e}"}), 500


@app.route('/final_video/<filename>')
def serve_final_video(filename):
    """Serves the completed translated video file."""
    safe_filename = secure_filename(filename)
    if FINAL_VIDEO_SUFFIX not in safe_filename or not safe_filename.endswith(FINAL_VIDEO_EXTENSION): abort(403)
    if safe_filename != filename: abort(403)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    if not os.path.exists(file_path): abort(404)
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_filename, as_attachment=False)


@app.route('/<path:filename>')
def serve_static(filename):
     """Serves static files (CSS, JS)."""
     if filename in ('styles.css', 'script.js'):
          return send_from_directory(BASE_DIR, filename)
     else: abort(404)


# --- Main Execution ---
# if __name__ == '__main__':
    # Dependency Checks
#    print("--- Dependency Checks ---")
#    if shutil.which("ffmpeg") is None: print("\nWARNING: FFmpeg not found in PATH. Processing WILL FAIL.\n")
#   else: print("FFmpeg found.")
#    if shutil.which("yt-dlp") is None: print("\nWARNING: yt-dlp not found in PATH. YouTube downloads WILL FAIL.\n")
#   else: print("yt-dlp found.")
#    print("Checking edge-tts...")
#    try: asyncio.run(edge_tts.list_voices()); print("edge-tts check successful.")
#    except Exception as e: print(f"\nWARNING: edge-tts check failed: {e}. TTS might fail.\n")
#    try: _ = AudioSegment.silent(duration=10); print("pydub check successful.")
#    except Exception as e: print(f"\nWARNING: pydub check failed: {e}\n")
#    print("-------------------------")

#    print(f"\nServing frontend from base directory: {BASE_DIR}")
#    print(f"Uploads, Jobs, Temp, and Final Videos folder: {UPLOAD_FOLDER}")
#    app.run(debug=True, host='127.0.0.1', port=5000)

# --- END OF app.py ---
