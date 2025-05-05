# --- START OF app.py (Review Translated Text - Complete) ---

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
from pytubefix import YouTube # Using pytubefix for potential fixes
from pytube import exceptions as pytube_exceptions # Import exceptions correctly
from pytubefix.cli import on_progress # Keep progress callback
import subprocess
import json
import math
import shutil # For directory cleanup
import traceback # For detailed error logging

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads') # Store uploads/jobs here
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Ensure upload folder exists

# Define subdirectories within UPLOAD_FOLDER
JOBS_FOLDER = os.path.join(UPLOAD_FOLDER, 'jobs')
os.makedirs(JOBS_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'mpeg', 'mpg'}
# Intermediate file extensions/suffixes
ORIGINAL_VIDEO_FILENAME = 'original_video' # Use consistent name within job dir
EXTRACTED_AUDIO_FILENAME = 'original_audio.wav'
CHUNK_FILENAME_PREFIX = 'chunk_'
CHUNK_AUDIO_EXTENSION = '.wav'
METADATA_FILENAME = 'metadata.json'
TTS_CHUNK_SUFFIX = '_tts.mp3'
COMBINED_TTS_FILENAME = 'combined_audio.mp3'
FINAL_VIDEO_SUFFIX = '_translated' # Keep final suffix consistent
FINAL_VIDEO_EXTENSION = '.mp4'

# Other Settings
TARGET_LANGUAGE = 'ta'
TARGET_LOCALE = 'ta-IN' # Tamil (India) - Adjust if needed e.g., ta-LK
MAX_CONTENT_LENGTH = 200 * 1024 * 1024 # 200 MB Limit
DEFAULT_TTS_VOICE = 'female'
MIN_SILENCE_LEN_MS = 700  # Minimum length of silence to split on (milliseconds)
SILENCE_THRESH_DBFS = -40 # Anything quieter than this is considered silence (dBFS)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER # Base upload dir
app.config['JOBS_FOLDER'] = JOBS_FOLDER     # Specific dir for job data
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
# IMPORTANT: Replace this with a strong, random secret key in a real deployment
app.config['SECRET_KEY'] = 'a-very-insecure-default-key-please-change'

# --- Helper Functions ---

def allowed_file(filename):
    """Checks if the file's extension is allowed."""
    return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_audio(video_path, output_audio_path):
    """Extracts audio from video file and saves it as WAV."""
    print(f"Extracting audio from: {video_path} to {output_audio_path}")
    video_clip = None; audio_clip = None # Initialize
    try:
        video_clip = mp.VideoFileClip(video_path)
        audio_clip = video_clip.audio
        if audio_clip is None:
            print("Error: No audio track found in the video.")
            return False, "No audio track found."
        # Ensure output is WAV (pcm_s16le is standard for WAV)
        audio_clip.write_audiofile(output_audio_path, codec='pcm_s16le')
        print(f"Audio extracted successfully to: {output_audio_path}")
        time.sleep(1) # Give time for file handle release
        return True, "Audio extracted successfully."
    except Exception as e:
        print(f"Error extracting audio: {e}")
        traceback.print_exc() # Log full traceback
        return False, f"Error during audio extraction: {str(e)}"
    finally:
        # Close resources safely
        if audio_clip:
             try: audio_clip.close()
             except Exception: pass
        if video_clip:
             try: video_clip.close()
             except Exception: pass

def transcribe_audio_chunk(audio_chunk_path):
    """Transcribes a single audio chunk file (WAV)."""
    print(f"Transcribing audio chunk: {os.path.basename(audio_chunk_path)}")
    recognizer = sr.Recognizer()
    text = None
    message = "Transcription failed."
    try:
        if not os.path.exists(audio_chunk_path):
            return None, f"Audio chunk file not found at {audio_chunk_path}"
        with sr.AudioFile(audio_chunk_path) as source:
            # Adjust for noise? recognizer.adjust_for_ambient_noise(source)
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='en-US')
            message = "Transcription successful."
    except sr.UnknownValueError:
        message = "Audio chunk not understood."
        print(f"Warning: {message} for {os.path.basename(audio_chunk_path)}")
    except sr.RequestError as e:
        message = f"API request failed for chunk; {e}"
        print(f"Warning: {message} for {os.path.basename(audio_chunk_path)}")
    except Exception as e:
        message = f"Chunk transcription failed: {str(e)}"
        print(f"Error: {message} for {os.path.basename(audio_chunk_path)}")
        traceback.print_exc()
    return text, message

def translate_text(text_to_translate):
    """Translates text chunk."""
    if not text_to_translate:
        return None, "No text provided for translation."
    try:
        time.sleep(0.1) # Avoid rapid requests to translator
        translated_text = GoogleTranslator(source='auto', target=TARGET_LANGUAGE).translate(text_to_translate)
        # Basic check for empty/failed translation
        if not translated_text:
             print("Warning: Translation returned empty result.")
             return None, "Translation returned empty result."
        return translated_text, "Translation successful."
    except Exception as e:
        error_message = f"Translation chunk failed: {str(e)}"
        print(f"Error: {error_message}")
        # traceback.print_exc() # Can be noisy
        return None, error_message

def synthesize_speech_chunk(text_to_speak, output_filename, voice_preference):
    """Synthesizes speech for a text chunk using edge-tts and saves to MP3."""
    if not text_to_speak:
        print(f"Warning: No text provided for speech synthesis chunk ({os.path.basename(output_filename)}). Skipping.")
        return False, "No text for chunk synth.", None

    target_gender = voice_preference.capitalize()

    async def find_and_synthesize_chunk_async():
        """Async helper for single chunk synthesis."""
        selected_voice_short_name = None
        try:
            voices = await edge_tts.list_voices()
            matching_voices = [v for v in voices if v['Locale'].lower() == TARGET_LOCALE.lower() and v['Gender'] == target_gender]

            if matching_voices:
                selected_voice = random.choice(matching_voices)
                selected_voice_short_name = selected_voice['ShortName']
                # print(f"Using voice {selected_voice_short_name} for chunk.") # Debug
            else: # Fallback to other gender
                fallback_gender = 'Male' if target_gender == 'Female' else 'Female'
                fallback_voices = [v for v in voices if v['Locale'].lower() == TARGET_LOCALE.lower() and v['Gender'] == fallback_gender]
                if fallback_voices:
                    selected_voice = random.choice(fallback_voices)
                    selected_voice_short_name = selected_voice['ShortName']
                    print(f"Warning: Using fallback {fallback_gender} voice for chunk: {selected_voice_short_name}")
                else:
                     print(f"Error: No suitable voices found for locale {TARGET_LOCALE} via edge-tts.")
                     return False, f"No suitable {TARGET_LOCALE} voice found.", None

            if not selected_voice_short_name:
                 return False, f"Could not select voice for {TARGET_LOCALE}", None

            # print(f"Synthesizing chunk: {text_to_speak[:30]}...") # Debug
            communicate = edge_tts.Communicate(text_to_speak, selected_voice_short_name)
            await communicate.save(output_filename)

            if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
                try:
                    duration_ms = len(AudioSegment.from_mp3(output_filename))
                    return True, "Chunk synth OK.", duration_ms
                except Exception as dur_err:
                    print(f"Warning: Could not get duration for {output_filename}: {dur_err}")
                    return True, "Chunk synth OK (duration unknown).", None # Still success
            else:
                error_msg = f"Chunk synth failed (edge-tts save error or file empty: {os.path.basename(output_filename)})."
                if os.path.exists(output_filename): os.remove(output_filename)
                return False, error_msg, None
        except Exception as e:
            error_message = f"Chunk synth failed (edge-tts error): {e}"
            # traceback.print_exc() # Can be noisy
            if os.path.exists(output_filename):
                try: os.remove(output_filename)
                except Exception: pass
            return False, error_message, None

    # Run async helper
    try:
        success, message, duration = asyncio.run(find_and_synthesize_chunk_async())
        return success, message, duration
    except RuntimeError as e:
        if "cannot run loop while another loop is running" in str(e):
             print("Warning: Asyncio loop conflict detected. Getting existing loop.")
             loop = asyncio.get_event_loop()
             success, message, duration = loop.run_until_complete(find_and_synthesize_chunk_async())
             return success, message, duration
        else:
             print(f"Error running asyncio task for chunk: {e}")
             traceback.print_exc()
             return False, f"Chunk synth failed: asyncio error {e}", None
    except Exception as e:
        print(f"Unexpected error during async chunk execution: {e}")
        traceback.print_exc()
        return False, f"Chunk synth failed: Unexpected error {e}", None

def replace_video_audio(original_video_path, new_audio_path, output_video_path):
    """Replaces the audio of a video file with a new audio file."""
    print(f"Replacing audio in '{os.path.basename(original_video_path)}' with '{os.path.basename(new_audio_path)}'")
    video_clip=None; audio_clip=None; final_video=None; # Initialize vars
    try:
        if not os.path.exists(original_video_path):
            return False, "Original video not found for merge."
        if not os.path.exists(new_audio_path):
            return False, "Combined audio not found for merge."

        video_clip = mp.VideoFileClip(original_video_path)
        audio_clip = mp.AudioFileClip(new_audio_path) # Works for MP3
        # Ensure audio duration doesn't drastically exceed video duration? Optional.
        # if abs(video_clip.duration - audio_clip.duration) > 1.0 : # If diff > 1 sec
        #    print(f"Warning: Audio duration ({audio_clip.duration:.2f}s) differs significantly from video duration ({video_clip.duration:.2f}s).")
            # audio_clip = audio_clip.subclip(0, video_clip.duration) # Trim audio? Risky.

        final_video = video_clip.set_audio(audio_clip)

        print(f"Writing final video: {output_video_path}")
        final_video.write_videofile(
            output_video_path,
            codec='libx264', audio_codec='aac',
            temp_audiofile=f"{os.path.splitext(output_video_path)[0]}_temp_audio.m4a",
            remove_temp=True, preset='medium', threads=4, logger='bar'
        )
        print(f"Final video saved successfully: {output_video_path}")
        return True, "Video creation successful."
    except Exception as e:
        error_message = f"Failed to replace video audio: {str(e)}"
        print(f"Error: {error_message}")
        traceback.print_exc()
        if os.path.exists(output_video_path):
            try: os.remove(output_video_path)
            except Exception as rm_err: print(f"Warning: Could not remove failed output video {output_video_path}: {rm_err}")
        return False, f"Video creation failed: {error_message}"
    finally: # Ensure clips are closed
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
    """Downloads YouTube video using yt-dlp."""
    output_template = os.path.join(output_path, filename)
    command = [
        'yt-dlp',
        '-f', 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best', # Limit resolution?
        '--merge-output-format', 'mp4',
        '-o', output_template,
        '--socket-timeout', '30', # 30 second timeout
        # '--max-filesize', '200M', # Optional: Limit download size directly?
        url
    ]
    try:
        print(f"Attempting download with yt-dlp: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        print(f"yt-dlp download successful for: {filename}")
        return True, "Download successful (yt-dlp)"
    except subprocess.CalledProcessError as e:
        error_output = e.stderr or "No stderr output from yt-dlp"
        print(f"yt-dlp failed. Return code: {e.returncode}")
        print(f"Error Output (yt-dlp):\n{error_output[:500]}...")
        return False, f"yt-dlp download failed: {error_output[:200]}..."
    except FileNotFoundError:
        print("Error: yt-dlp command not found. Is it installed and in PATH?")
        return False, "yt-dlp command not found."
    except Exception as e:
        print(f"An unexpected error occurred with yt-dlp: {e}")
        traceback.print_exc()
        return False, f"Unexpected error with yt-dlp: {str(e)}"

# --- Stage 1 Processing Function ---
def process_stage1(input_path, base_filename, is_youtube):
    """Handles Stage 1: Extraction, Segmentation, Transcription, Translation."""
    job_id = f"{int(time.time())}_{secure_filename(base_filename)}"
    job_dir = os.path.join(app.config['JOBS_FOLDER'], job_id)
    chunks_dir = os.path.join(job_dir, 'chunks')
    os.makedirs(chunks_dir, exist_ok=True)

    original_ext = os.path.splitext(input_path)[1] if not is_youtube else '.mp4'
    original_video_target_path = os.path.join(job_dir, ORIGINAL_VIDEO_FILENAME + original_ext)
    extracted_audio_path = os.path.join(job_dir, EXTRACTED_AUDIO_FILENAME)
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)

    metadata = {
        'job_id': job_id,
        'base_filename': base_filename,
        'original_video_path': original_video_target_path,
        'chunks': [],
        'status': 'Stage1_Processing'
    }
    input_path_handled = False # Flag to track if input file was moved/deleted

    try:
        # --- Step 0: Move/Copy original video ---
        print(f"Preparing input video for job {job_id}...")
        try:
            shutil.move(input_path, original_video_target_path)
            print(f"Moved input video to job directory: {os.path.basename(original_video_target_path)}")
            input_path_handled = True
        except Exception as move_err:
             try:
                 print(f"Move failed ({move_err}), attempting copy...")
                 shutil.copy2(input_path, original_video_target_path)
                 print(f"Copied input video to job directory: {os.path.basename(original_video_target_path)}")
                 try: os.remove(input_path); print("Removed original input file after copy.")
                 except Exception as del_err: print(f"Warning: Failed to remove original input after copy: {del_err}")
                 input_path_handled = True
             except Exception as copy_err:
                  raise ValueError(f"Failed to move/copy input video to job dir: {copy_err}")

        # --- Step 1: Extract Audio ---
        success, msg = extract_audio(original_video_target_path, extracted_audio_path)
        if not success or not os.path.exists(extracted_audio_path):
             raise ValueError(f"Audio extraction failed: {msg}")

        # --- Step 2: Load & Segment ---
        print("Loading and segmenting audio...")
        sound = AudioSegment.from_wav(extracted_audio_path)
        nonsilent_ranges = detect_nonsilent(sound, min_silence_len=MIN_SILENCE_LEN_MS, silence_thresh=SILENCE_THRESH_DBFS, seek_step=1)
        if not nonsilent_ranges: raise ValueError("No speech detected in the audio.")
        print(f"Detected {len(nonsilent_ranges)} non-silent segments.")

        # --- Step 3 & 4: Transcribe & Translate Chunks ---
        last_chunk_end = 0
        for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
            print(f"\nProcessing Chunk {i+1}/{len(nonsilent_ranges)}...")
            silence_before = start_ms - last_chunk_end
            if silence_before < 0: silence_before = 0

            chunk_audio = sound[start_ms:end_ms]
            chunk_filename = f"{CHUNK_FILENAME_PREFIX}{i}{CHUNK_AUDIO_EXTENSION}"
            chunk_path = os.path.join(chunks_dir, chunk_filename)

            try: chunk_audio.export(chunk_path, format="wav")
            except Exception as export_err:
                 print(f"Warning: Failed to export chunk {i} audio: {export_err}. Skipping.")
                 continue # Skip this chunk entirely if export fails

            transcribed_text, trans_msg = transcribe_audio_chunk(chunk_path)
            print(f"  Transcription: {trans_msg}")

            source_text_for_translation = transcribed_text or ""
            translated_text, translate_msg = translate_text(source_text_for_translation)
            print(f"  Translation: {translate_msg}")

            metadata['chunks'].append({
                'index': i,
                'start_ms': start_ms,
                'end_ms': end_ms,
                'silence_before_ms': silence_before,
                'original_audio_chunk': chunk_filename,
                'transcribed_text': transcribed_text or "",
                'translated_text': translated_text or "",
                'transcription_status': trans_msg,
                'translation_status': translate_msg
            })
            last_chunk_end = end_ms

        # --- Mark Stage 1 Complete ---
        metadata['status'] = 'Stage1_Completed_Translation_Pending_Review'
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)

        print(f"Stage 1 (incl. Translation) completed for job {job_id}")
        return True, "Ready for translation review.", metadata

    except Exception as e:
        print(f"Error during Stage 1 for {job_id}: {e}")
        traceback.print_exc()
        # Clean up job directory on failure
        if os.path.exists(job_dir):
            print(f"Cleaning up failed job directory: {job_dir}")
            try: shutil.rmtree(job_dir)
            except Exception as clean_err: print(f"Warning: Failed cleanup {job_dir}: {clean_err}")
        # Clean up original input if it wasn't moved/deleted yet
        if not input_path_handled and input_path and os.path.exists(input_path):
             try: os.remove(input_path); print(f"Cleaned up original input after stage 1 failure: {input_path}")
             except Exception as del_err: print(f"Warning: Failed to cleanup original input after stage 1 failure: {del_err}")
        return False, f"Processing failed during Stage 1: {str(e)}", None


# --- Final Stage Processing Function ---
def process_final_stage(job_id, edited_translated_texts, tts_voice):
    """Handles Final Stage: TTS (using edited translated text), Reconstruct, Merge."""
    job_dir = os.path.join(app.config['JOBS_FOLDER'], job_id)
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)
    chunks_dir = os.path.join(job_dir, 'chunks')
    combined_audio_path = os.path.join(job_dir, COMBINED_TTS_FILENAME)
    metadata = {}
    final_video_filename_base = "final_output" # Default

    try:
        # --- Load Metadata ---
        if not os.path.exists(metadata_path): raise ValueError("Metadata file not found.")
        with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)

        current_status = metadata.get('status')
        if current_status != 'Stage1_Completed_Translation_Pending_Review' and not current_status.startswith('FinalStage_Failed'):
             raise ValueError(f"Job {job_id} not ready for final processing (Status: {current_status})")
        elif current_status.startswith('FinalStage_Failed'):
             print(f"Retrying Final Stage for job {job_id} which previously failed.")

        metadata['status'] = 'FinalStage_Processing'
        try: # Save status update
             with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        except Exception as meta_write_err: print(f"Warning: Could not update metadata status: {meta_write_err}")

        final_video_filename_base = metadata.get('base_filename', job_id)

        # --- Synthesize chunks using EDITED TRANSLATED text ---
        print(f"--- Starting Final Stage for Job {job_id} ---")
        final_audio = AudioSegment.empty()
        all_tts_failed = True # Assume failure until one succeeds

        for i, chunk_meta in enumerate(metadata['chunks']):
            chunk_index = chunk_meta['index']
            silence_before = chunk_meta['silence_before_ms']
            edited_translated_text = edited_translated_texts.get(str(chunk_index))

            print(f"\nProcessing chunk {chunk_index} for TTS...")
            print(f"  Silence before: {silence_before} ms")
            # print(f"  Using Edited Translated Text: {edited_translated_text[:60] if edited_translated_text else 'N/A'}...") # Verbose

            if silence_before > 0: final_audio += AudioSegment.silent(duration=silence_before)
            if not edited_translated_text:
                 print("  Skipping TTS for empty edited translated text.")
                 continue

            tts_chunk_filename = f"{CHUNK_FILENAME_PREFIX}{chunk_index}{TTS_CHUNK_SUFFIX}"
            tts_chunk_path = os.path.join(chunks_dir, tts_chunk_filename)
            success, msg, duration = synthesize_speech_chunk(edited_translated_text, tts_chunk_path, tts_voice)

            if success:
                 all_tts_failed = False # At least one succeeded
                 print(f"  TTS successful for chunk {chunk_index}.")
                 try:
                      tts_segment = AudioSegment.from_mp3(tts_chunk_path)
                      final_audio += tts_segment
                 except Exception as load_err:
                      print(f"  Warning: Failed to load successful TTS chunk {chunk_index} from {tts_chunk_path}: {load_err}")
            else:
                 print(f"  Warning: TTS failed for chunk {chunk_index}: {msg}")

        # --- Export Combined Audio ---
        if len(final_audio) == 0:
            if all_tts_failed:
                 raise ValueError("No audio generated in Final Stage (All TTS failed or skipped).")
            else:
                 raise ValueError("Failed to reconstruct audio track (final audio empty despite some TTS success?).")

        print(f"\nExporting combined audio (Duration: {len(final_audio)/1000:.2f}s)...")
        final_audio.export(combined_audio_path, format="mp3")

        # --- Replace Video Audio ---
        original_video_path = metadata['original_video_path']
        if not os.path.exists(original_video_path):
             raise ValueError(f"Original video path in metadata not found: {original_video_path}")

        final_video_output_filename = f"{secure_filename(final_video_filename_base)}{FINAL_VIDEO_SUFFIX}{FINAL_VIDEO_EXTENSION}" # Sanitize base
        final_video_output_path = os.path.join(app.config['UPLOAD_FOLDER'], final_video_output_filename)

        success, msg = replace_video_audio(original_video_path, combined_audio_path, final_video_output_path)
        if not success: raise ValueError(f"Failed to create final video: {msg}")

        # --- Success & Cleanup ---
        print(f"Final Stage completed. Cleaning up job directory: {job_dir}")
        try:
            shutil.rmtree(job_dir)
            print(f"Successfully removed job directory: {job_dir}")
        except Exception as clean_err:
             print(f"Warning: Failed to cleanup completed job dir {job_dir}: {clean_err}")

        return True, "Video processing complete!", {'final_video_filename': final_video_output_filename}

    except Exception as e:
        print(f"Error during Final Stage for job {job_id}: {e}")
        traceback.print_exc()
        metadata['status'] = f'FinalStage_Failed: {str(e)[:100]}'
        try: # Try update metadata status
             with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        except Exception as meta_err: print(f"Warning: Could not update metadata on final stage failure: {meta_err}")
        # Keep job dir on failure
        return False, f"Processing failed during Final Stage: {e}", None

# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/process-stage1', methods=['POST'])
def handle_process_stage1():
    """Handles initial video upload or URL, starts Stage 1 processing."""
    tts_voice = request.form.get('tts_voice', DEFAULT_TTS_VOICE)
    input_path = None
    base_filename = None
    is_youtube = False
    temp_file_to_delete = None

    try:
        # --- Handle File Upload ---
        if 'videoFile' in request.files:
            file = request.files['videoFile']
            if file.filename == '': return jsonify({"message": "No file selected"}), 400
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                base_filename = os.path.splitext(original_filename)[0]
                temp_upload_filename = f"temp_{int(time.time())}_{original_filename}"
                temp_upload_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_upload_filename)
                file.save(temp_upload_path)
                input_path = temp_upload_path
                temp_file_to_delete = input_path
                print(f"File uploaded temporarily to: {input_path}")
            else: return jsonify({"message": "File type not allowed"}), 400
        # --- Handle YouTube URL ---
        elif 'youtube_url' in request.form:
            youtube_url = request.form['youtube_url']
            if not youtube_url: return jsonify({"message": "Missing YouTube URL"}), 400
            is_youtube = True
            print(f"Processing YouTube URL: {youtube_url}")
            base_filename_title = "youtube_video" # Use generic base for YT now
            timestamp = int(time.time())
            base_filename = f"{base_filename_title}_{timestamp}"
            temp_download_filename = base_filename + ".mp4"
            temp_download_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_download_filename)
            dl_success, dl_msg = download_with_yt_dlp(youtube_url, app.config['UPLOAD_FOLDER'], temp_download_filename)
            if not dl_success: raise ValueError(f"YouTube download failed: {dl_msg}")
            input_path = temp_download_path
            temp_file_to_delete = input_path
            print(f"YouTube video downloaded temporarily to: {input_path}")
        else: return jsonify({"message": "No video file or YouTube URL provided"}), 400

        if not input_path or not base_filename: raise ValueError("Internal error: Input path/base filename not set.")

        # --- Call Stage 1 ---
        success, message, metadata = process_stage1(input_path, base_filename, is_youtube)
        # input_path (temp file) should have been moved or deleted by process_stage1 now
        temp_file_to_delete = None # Clear flag as it's handled

        if success:
            metadata['tts_voice'] = tts_voice # Store voice choice
            job_dir = os.path.join(app.config['JOBS_FOLDER'], metadata['job_id'])
            metadata_path = os.path.join(job_dir, METADATA_FILENAME)
            try:
                 with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
            except Exception as write_err: print(f"Warning: Failed to save metadata: {write_err}")
            return jsonify({"message": message, "review_data": metadata}), 200
        else: return jsonify({"message": message}), 500

    except Exception as e:
        print(f"Error in /process-stage1 route: {e}")
        traceback.print_exc()
        # Clean up temp file if it exists and wasn't handled by stage1 failure
        if temp_file_to_delete and os.path.exists(temp_file_to_delete):
             print(f"Cleaning up temporary file due to error in route: {temp_file_to_delete}")
             try: os.remove(temp_file_to_delete)
             except Exception as del_err: print(f"Warning: Failed cleanup for {temp_file_to_delete}: {del_err}")
        return jsonify({"message": f"An unexpected error occurred: {str(e)}"}), 500


@app.route('/serve-chunk/<job_id>/<chunk_filename>')
def serve_chunk(job_id, chunk_filename):
    """Serves original audio chunk files for download during review."""
    safe_job_id = secure_filename(job_id)
    safe_chunk_filename = secure_filename(chunk_filename)
    if safe_job_id != job_id or safe_chunk_filename != chunk_filename: abort(403)
    job_dir = os.path.join(app.config['JOBS_FOLDER'], safe_job_id)
    chunks_dir = os.path.join(job_dir, 'chunks')
    file_path = os.path.join(chunks_dir, safe_chunk_filename)
    if not os.path.exists(file_path) or not os.path.abspath(file_path).startswith(os.path.abspath(chunks_dir)): abort(404)
    print(f"Serving chunk: {file_path}")
    return send_from_directory(chunks_dir, safe_chunk_filename, as_attachment=True)


@app.route('/process-final-stage', methods=['POST'])
def handle_process_final_stage():
    """Receives edited translated texts and triggers the final TTS/Merge stage."""
    data = request.get_json()
    if not data or 'job_id' not in data or 'edited_translated_texts' not in data:
         print("Bad Request: Missing job_id or edited_translated_texts")
         return jsonify({"message": "Missing job_id or edited_translated_texts"}), 400

    job_id = data['job_id']
    edited_translated_texts = data['edited_translated_texts']
    tts_voice = data.get('tts_voice', DEFAULT_TTS_VOICE) # Get voice from payload as fallback

    safe_job_id = secure_filename(job_id)
    if safe_job_id != job_id: return jsonify({"message": "Invalid job ID format"}), 400
    job_dir = os.path.join(app.config['JOBS_FOLDER'], safe_job_id)
    if not os.path.isdir(job_dir): return jsonify({"message": "Job not found"}), 404

    # Retrieve voice from metadata as primary source
    metadata_path = os.path.join(job_dir, METADATA_FILENAME)
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
            tts_voice = metadata.get('tts_voice', tts_voice)
            print(f"Using TTS voice '{tts_voice}' from metadata for job {job_id}")
        except Exception as read_err: print(f"Warning: Could not read metadata ({read_err}). Using voice '{tts_voice}'.")

    try:
        success, message, results = process_final_stage(safe_job_id, edited_translated_texts, tts_voice)
        status_code = 200 if success else 500
        return jsonify({"message": message, **(results or {})}), status_code
    except Exception as e:
        print(f"Error in /process-final-stage route for job {job_id}: {e}")
        traceback.print_exc()
        return jsonify({"message": f"An unexpected error occurred during final processing: {str(e)}"}), 500


@app.route('/final_video/<filename>')
def serve_final_video(filename):
    """Serves the completed translated video file."""
    safe_filename = secure_filename(filename)
    if FINAL_VIDEO_SUFFIX not in safe_filename or not safe_filename.endswith(FINAL_VIDEO_EXTENSION): abort(403)
    if safe_filename != filename: abort(403)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
    if not os.path.exists(file_path): abort(404)
    print(f"Serving final video: {safe_filename}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_filename, as_attachment=False)


@app.route('/<path:filename>')
def serve_static(filename):
     """Serves static files (CSS, JS) required by the frontend."""
     if filename in ('styles.css', 'script.js'):
          return send_from_directory(BASE_DIR, filename)
     else: abort(404)


# --- Main Execution ---
if __name__ == '__main__':
    # Dependency Checks
    print("--- Dependency Checks ---")
    if shutil.which("ffmpeg") is None: print("\nWARNING: FFmpeg not found in PATH. Processing WILL FAIL.\n")
    else: print("FFmpeg found.")
    if shutil.which("yt-dlp") is None: print("\nWARNING: yt-dlp not found in PATH. YouTube downloads WILL FAIL.\n")
    else: print("yt-dlp found.")
    print("Checking edge-tts...")
    try: asyncio.run(edge_tts.list_voices()); print("edge-tts check successful.")
    except Exception as e: print(f"\nWARNING: edge-tts check failed: {e}. TTS might fail.\n")
    try: _ = AudioSegment.silent(duration=10); print("pydub check successful.")
    except Exception as e: print(f"\nWARNING: pydub check failed: {e}\n")
    print("-------------------------")

    print(f"\nServing frontend from base directory: {BASE_DIR}")
    print(f"Uploads, Jobs, and Final Videos folder: {UPLOAD_FOLDER}")
    app.run(debug=True, host='127.0.0.1', port=5000)

# --- END OF app.py ---