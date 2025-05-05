// --- START OF script.js (Review Pref - Complete) ---
document.addEventListener('DOMContentLoaded', () => {
    // --- Get DOM Elements ---
    const uploadButton = document.getElementById('uploadButton');
    const videoFileInput = document.getElementById('videoFile');
    const fileFeedback = document.getElementById('fileFeedback');
    const youtubeUrlInput = document.getElementById('youtubeUrl');
    const processUrlButton = document.getElementById('processUrlButton');
    const voiceOptionsContainer = document.getElementById('voiceOptionsContainer');
    const reviewOptionsContainer = document.getElementById('reviewOptionsContainer'); // New container
    const inputSection = document.getElementById('inputSection');

    const mainFeedbackArea = document.getElementById('mainFeedbackArea');
    const progressIndicator = document.getElementById('progressIndicator');
    const progressStep = document.getElementById('progressStep');

    // --- Elements for review stage ---
    const reviewSection = document.getElementById('reviewSection');
    const reviewContent = document.getElementById('reviewContent');
    const submitEditsButton = document.getElementById('submitEditsButton');
    const currentJobIdInput = document.getElementById('currentJobId'); // Hidden input

    let isProcessingStage1 = false; // Flag for initial processing (stage 1 or direct)
    let isProcessingFinalStage = false; // Flag specifically for final stage after review

    // --- Event Listeners ---

    // 1. File Upload Button Click -> Trigger File Input
    if (uploadButton && videoFileInput) {
        uploadButton.addEventListener('click', () => {
            if (isProcessingStage1 || isProcessingFinalStage) {
                setFeedback('Processing already in progress. Please wait.', 'info'); return;
            }
            videoFileInput.click();
        });
    }

    // 2. File Input Change -> Start Processing
    if (videoFileInput) {
        videoFileInput.addEventListener('change', (event) => {
            if (isProcessingStage1 || isProcessingFinalStage) return;
            const files = event.target.files;
            if (files.length > 0) {
                const selectedFile = files[0];
                if (selectedFile.type.startsWith('video/') || allowedFileExtension(selectedFile.name)) {
                    fileFeedback.textContent = `Selected: ${selectedFile.name}`;
                    fileFeedback.style.color = '#28a745';
                    const formData = createInitialFormData(selectedFile); // Use new function
                    handleInitialProcessingStart('/process-stage1', formData, selectedFile.name); // Call unified handler
                } else {
                    fileFeedback.textContent = 'Please select a valid video file (mp4, mov, avi, mkv, etc.).';
                    fileFeedback.style.color = '#dc3545';
                    videoFileInput.value = '';
                }
            } else {
                fileFeedback.textContent = 'No file selected.';
                fileFeedback.style.color = '#666';
            }
        });
    }

    // 3. Process URL Button Click -> Start Processing
    if (processUrlButton && youtubeUrlInput) {
        processUrlButton.addEventListener('click', () => {
            if (isProcessingStage1 || isProcessingFinalStage) {
                setFeedback('Processing already in progress. Please wait.', 'info'); return;
            }
            const url = youtubeUrlInput.value.trim();
            if (!url) { setFeedback('Please enter a YouTube URL.', 'error'); return; }
            if (!url.includes('youtube.com/') && !url.includes('youtu.be/')) {
                 setFeedback('Please enter a valid YouTube URL.', 'error'); return;
            }
            const formData = createInitialFormData(null, url); // Use new function
            handleInitialProcessingStart('/process-stage1', formData, url); // Call unified handler
        });
    }

    // 4. Submit Edits Button Click -> Start Final Stage (Only relevant in Review mode)
    if (submitEditsButton) {
         submitEditsButton.addEventListener('click', () => {
              if (isProcessingStage1 || isProcessingFinalStage) {
                   setFeedback('Processing already in progress. Please wait.', 'info'); return;
              }
              handleReviewSubmission(); // This remains for review mode submission
         });
    }


    // --- Helper Functions ---

    function allowedFileExtension(filename) {
        const allowed = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'mpeg', 'mpg'];
        const ext = filename.split('.').pop().toLowerCase();
        return allowed.includes(ext);
    }

    // NEW function to create form data including review preference
    function createInitialFormData(file, url = null) {
        const formData = new FormData();
        if (file) {
            formData.append('videoFile', file);
        } else if (url) {
            formData.append('youtube_url', url);
        }
        // Get voice preference
        const selectedVoice = voiceOptionsContainer.querySelector('input[name="ttsVoice"]:checked').value || 'female';
        formData.append('tts_voice', selectedVoice);
        // Get review preference
        const reviewPreference = reviewOptionsContainer.querySelector('input[name="reviewPreference"]:checked').value || 'direct';
        formData.append('reviewPreference', reviewPreference);

        console.log("Sending Review Preference:", reviewPreference); // Debug
        return formData;
    }

    // --- Handle Start of EITHER Direct OR Stage 1 Processing ---
    function handleInitialProcessingStart(endpoint, payload, inputName) {
        if (isProcessingStage1 || isProcessingFinalStage) return;
        isProcessingStage1 = true; // Use this flag for the initial request
        disableUIBeforeProcessing();
        const reviewPref = payload.get('reviewPreference') || 'direct'; // Get pref from form data
        const processingModeText = reviewPref === 'review' ? "Stage 1 (Segmentation, Transcription & Translation)" : "Direct Processing";
        setFeedback(`Starting ${processingModeText} for: ${inputName}`, 'info');
        progressStep.textContent = 'Processing Video... This may take a while.';
        progressIndicator.style.display = 'flex';
        hideReviewUI();

        fetch(endpoint, { method: 'POST', body: payload })
            .then(async response => {
                if (!response.ok) {
                    let errorMsg = `Server error: ${response.status}`;
                    try { errorMsg = (await response.json()).message || errorMsg; }
                    catch (e) { try {errorMsg = await response.text()} catch(e2) {/* ignore */} }
                    throw new Error(errorMsg);
                }
                return response.json();
            })
            .then(data => {
                console.log("Initial Processing Response:", data);
                // --- Check the mode returned by the backend ---
                if (data.mode === 'review' && data.review_data) {
                    setFeedback(data.message || 'Translation complete. Please review.', 'success');
                    displayReviewUI(data.review_data); // Show review UI
                } else if (data.mode === 'direct' && data.final_video_filename) {
                    setFeedback(data.message || 'Direct processing complete!', 'success');
                    addDownloadLink(`/final_video/${data.final_video_filename}`, data.final_video_filename); // Add download link
                    enableUI(); // Re-enable UI for new job
                    resetInputs(); // Clear inputs
                } else {
                    // Unexpected response structure
                    throw new Error(data.message || "Unexpected response from server after initial processing.");
                }
            })
            .catch(error => {
                console.error('Initial Processing Fetch Error:', error);
                setFeedback(`Processing Failed: ${error.message}`, 'error');
                enableUI(); // Re-enable UI fully on failure
                resetInputs();
            })
            .finally(() => {
                isProcessingStage1 = false; // Clear initial processing flag
                progressIndicator.style.display = 'none';
                progressStep.textContent = '';
            });
    }

    // --- Display the Review UI (Remains the same, called only if mode is 'review') ---
    function displayReviewUI(reviewData) {
        currentJobIdInput.value = reviewData.job_id;
        reviewContent.innerHTML = ''; // Clear previous

        if (!reviewData.chunks || reviewData.chunks.length === 0) {
             reviewContent.innerHTML = '<p>No speech segments found or Stage 1 processing failed.</p>';
             reviewSection.style.display = 'block';
             submitEditsButton.style.display = 'none';
             enableUI(); // Enable main buttons as nothing to review
             inputSection.style.display = 'block';
             return;
        }

        reviewData.chunks.forEach(chunk => {
            const chunkDiv = document.createElement('div');
            chunkDiv.className = 'review-chunk';
            chunkDiv.innerHTML = `
                <h4>Chunk ${chunk.index + 1} (${(chunk.start_ms / 1000).toFixed(2)}s - ${(chunk.end_ms / 1000).toFixed(2)}s)</h4>
                <div class="transcription-original">
                    <strong>Original Transcription:</strong>
                    <p>${chunk.transcribed_text || '(Transcription failed or empty)'}</p>
                    <small>Status: ${chunk.transcription_status || 'N/A'}</small>
                </div>
                <hr>
                <label for="editedTranslatedText_${chunk.index}"><strong>Translated Text (Edit Below):</strong></label>
                 <small>Status: ${chunk.translation_status || 'N/A'}</small>
                <textarea id="editedTranslatedText_${chunk.index}" data-chunk-index="${chunk.index}" rows="4">${chunk.translated_text || ''}</textarea>
                <a href="/serve-chunk/${reviewData.job_id}/${chunk.original_audio_chunk}" target="_blank" download="${chunk.original_audio_chunk}">Listen to Original Chunk ${chunk.index + 1}</a>
            `;
            reviewContent.appendChild(chunkDiv);
        });

        inputSection.style.display = 'none'; // Hide initial inputs
        reviewSection.style.display = 'block'; // Show review section
        submitEditsButton.style.display = 'block'; // Show submit button
        progressIndicator.style.display = 'none';
        if(submitEditsButton) submitEditsButton.disabled = false; // Enable submit
    }

     // --- Hide the Review UI ---
     function hideReviewUI() {
          reviewSection.style.display = 'none';
          reviewContent.innerHTML = '';
          currentJobIdInput.value = '';
     }

    // --- Handle Submission of Edited TRANSLATED Text (Final Stage - Only for Review Mode) ---
    function handleReviewSubmission() {
        if (isProcessingStage1 || isProcessingFinalStage) return;
        isProcessingFinalStage = true; // Use flag for final stage
        disableUIBeforeProcessing();
        setFeedback('Starting Final Stage (TTS & Merging)...', 'info');
        progressStep.textContent = 'Generating Final Video... This may take a while.';
        progressIndicator.style.display = 'flex';

        const jobId = currentJobIdInput.value;
        const editedTranslatedTexts = {};
        const textAreas = reviewContent.querySelectorAll('textarea[data-chunk-index]');
        textAreas.forEach(ta => { editedTranslatedTexts[ta.dataset.chunkIndex] = ta.value; });

        const selectedVoice = voiceOptionsContainer.querySelector('input[name="ttsVoice"]:checked').value || 'female';

        fetch('/process-final-stage', { // Endpoint for review mode's final stage
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                 job_id: jobId,
                 edited_translated_texts: editedTranslatedTexts,
                 tts_voice: selectedVoice
            })
        })
        .then(async response => {
             if (!response.ok) {
                 let errorMsg = `Server error: ${response.status}`;
                 try { errorMsg = (await response.json()).message || errorMsg; } catch (e) { try {errorMsg = await response.text()} catch(e2) {/* ignore */} }
                 throw new Error(errorMsg);
             }
             return response.json();
        })
        .then(data => {
             console.log("Final Stage Success Data:", data);
             setFeedback(data.message || 'Processing complete!', 'success');
             if (data.final_video_filename) {
                  addDownloadLink(`/final_video/${data.final_video_filename}`, data.final_video_filename);
             }
             hideReviewUI();
             inputSection.style.display = 'block'; // Show initial inputs again
             enableUI();
             resetInputs(); // Clear inputs after success
        })
        .catch(error => {
             console.error('Final Stage Fetch Error:', error);
             setFeedback(`Final Stage Failed: ${error.message}`, 'error');
             // Keep review UI open, enable submit button for retry
             inputSection.style.display = 'none';
             reviewSection.style.display = 'block';
             if(submitEditsButton) submitEditsButton.disabled = false;
             enableMainInputButtons(); // Also enable voice options etc.
        })
        .finally(() => {
             isProcessingFinalStage = false;
             progressIndicator.style.display = 'none';
             progressStep.textContent = '';
             // Don't reset inputs here, only on success maybe
        });
    }


    function setFeedback(message, type = 'info') {
        console.log(`Feedback (${type}): ${message}`);
        const existingLinks = mainFeedbackArea.querySelectorAll('a');
        existingLinks.forEach(link => link.remove());
        mainFeedbackArea.textContent = message;
        mainFeedbackArea.className = `feedback-area ${type}`;
    }

    function addDownloadLink(fileUrlPath, filename) {
        try {
            console.log(`Adding download link for: ${filename} at ${fileUrlPath}`);
            const link = document.createElement('a');
            link.href = fileUrlPath;
            link.textContent = `Download/View ${filename}`;
            link.target = '_blank';
            link.style.display = 'block';
            link.style.marginTop = '10px';
            mainFeedbackArea.appendChild(link);
        } catch (e) {
            console.error("Error adding download link:", e);
            mainFeedbackArea.innerHTML += `<p style="color: red;">Error adding download link.</p>`;
        }
     }

    function disableUIBeforeProcessing() {
        disableMainInputButtons();
        if(submitEditsButton) submitEditsButton.disabled = true;
        // Disable review preference radio buttons too
        const reviewRadios = reviewOptionsContainer.querySelectorAll('input[type="radio"]');
        reviewRadios.forEach(radio => radio.disabled = true);
        progressIndicator.style.display = 'flex';
    }

    function disableMainInputButtons() {
        if(uploadButton) uploadButton.disabled = true;
        if(processUrlButton) processUrlButton.disabled = true;
        if(videoFileInput) videoFileInput.disabled = true;
        if(youtubeUrlInput) youtubeUrlInput.disabled = true;
         const voiceRadios = voiceOptionsContainer.querySelectorAll('input[type="radio"]');
         voiceRadios.forEach(radio => radio.disabled = true);
    }

    function enableUI() {
        enableMainInputButtons();
        // Submit button enabled only if review section is visible
        if(submitEditsButton) submitEditsButton.disabled = (reviewSection.style.display === 'none');
        // Enable review preference radio buttons
        const reviewRadios = reviewOptionsContainer.querySelectorAll('input[type="radio"]');
        reviewRadios.forEach(radio => radio.disabled = false);
    }

    function enableMainInputButtons() {
        if(uploadButton) uploadButton.disabled = false;
        if(processUrlButton) processUrlButton.disabled = false;
        if(videoFileInput) videoFileInput.disabled = false;
        if(youtubeUrlInput) youtubeUrlInput.disabled = false;
         const voiceRadios = voiceOptionsContainer.querySelectorAll('input[type="radio"]');
         voiceRadios.forEach(radio => radio.disabled = false);
    }

    function resetInputs() {
         if(videoFileInput) videoFileInput.value = '';
         if(fileFeedback) fileFeedback.textContent = 'No file selected.';
         if(youtubeUrlInput) youtubeUrlInput.value = '';
         // Optionally reset radio buttons to default?
         // document.getElementById('voiceFemale').checked = true;
         // document.getElementById('prefDirect').checked = true; // Reset review pref
    }

});
// --- END OF script.js ---
