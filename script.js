// --- START OF script.js (Review Translated Text - Complete) ---
document.addEventListener('DOMContentLoaded', () => {
    // --- Get DOM Elements ---
    const uploadButton = document.getElementById('uploadButton');
    const videoFileInput = document.getElementById('videoFile');
    const fileFeedback = document.getElementById('fileFeedback');
    const youtubeUrlInput = document.getElementById('youtubeUrl');
    const processUrlButton = document.getElementById('processUrlButton');
    const voiceOptionsContainer = document.getElementById('voiceOptionsContainer');
    const inputSection = document.getElementById('inputSection'); // Container for initial inputs

    const mainFeedbackArea = document.getElementById('mainFeedbackArea');
    const progressIndicator = document.getElementById('progressIndicator');
    const progressStep = document.getElementById('progressStep');

    // --- Elements for review stage ---
    const reviewSection = document.getElementById('reviewSection');
    const reviewContent = document.getElementById('reviewContent');
    const submitEditsButton = document.getElementById('submitEditsButton');
    const currentJobIdInput = document.getElementById('currentJobId'); // Hidden input

    let isProcessingStage1 = false;
    let isProcessingFinalStage = false;

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

    // 2. File Input Change -> Start Stage 1
    if (videoFileInput) {
        videoFileInput.addEventListener('change', (event) => {
            if (isProcessingStage1 || isProcessingFinalStage) return;
            const files = event.target.files;
            if (files.length > 0) {
                const selectedFile = files[0];
                if (selectedFile.type.startsWith('video/') || allowedFileExtension(selectedFile.name)) {
                    fileFeedback.textContent = `Selected: ${selectedFile.name}`;
                    fileFeedback.style.color = '#28a745';
                    const formData = createStage1FormData(selectedFile);
                    handleStage1Start('/process-stage1', formData, selectedFile.name);
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

    // 3. Process URL Button Click -> Start Stage 1
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
            const formData = createStage1FormData(null, url); // Pass URL
            handleStage1Start('/process-stage1', formData, url);
        });
    }

    // 4. Submit Edits Button Click -> Start Final Stage
    if (submitEditsButton) {
         submitEditsButton.addEventListener('click', () => {
              if (isProcessingStage1 || isProcessingFinalStage) {
                   setFeedback('Processing already in progress. Please wait.', 'info'); return;
              }
              handleReviewSubmission(); // Calls the function to start final stage
         });
    }


    // --- Helper Functions ---

    function allowedFileExtension(filename) {
        const allowed = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'mpeg', 'mpg'];
        const ext = filename.split('.').pop().toLowerCase();
        return allowed.includes(ext);
    }

    function createStage1FormData(file, url = null) {
        const formData = new FormData();
        if (file) {
            formData.append('videoFile', file);
        } else if (url) {
            formData.append('youtube_url', url);
        }
        const selectedVoice = document.querySelector('input[name="ttsVoice"]:checked').value || 'female';
        formData.append('tts_voice', selectedVoice);
        return formData;
    }

    // --- Handle Start of Stage 1 Processing ---
    function handleStage1Start(endpoint, payload, inputName) {
        if (isProcessingStage1 || isProcessingFinalStage) return;
        isProcessingStage1 = true;
        disableUIBeforeProcessing();
        setFeedback(`Starting Stage 1 (Segmentation, Transcription & Translation) for: ${inputName}`, 'info');
        progressStep.textContent = 'Extracting & Processing... This may take a while.';
        progressIndicator.style.display = 'flex'; // Show progress indicator
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
                console.log("Stage 1 Success Data:", data);
                setFeedback(data.message || 'Translation complete. Please review.', 'success');
                if (data.review_data) {
                     displayReviewUI(data.review_data); // Proceed to display review UI
                } else {
                     throw new Error("Missing review data from server.");
                }
            })
            .catch(error => {
                console.error('Stage 1 Fetch Error:', error);
                setFeedback(`Stage 1 Failed: ${error.message}`, 'error');
                enableUI(); // Re-enable UI fully on failure
            })
            .finally(() => {
                isProcessingStage1 = false;
                progressIndicator.style.display = 'none'; // Hide progress indicator
                progressStep.textContent = '';
            });
    }

    // --- Display the Review UI (for Translated Text) ---
    function displayReviewUI(reviewData) {
        currentJobIdInput.value = reviewData.job_id;
        reviewContent.innerHTML = ''; // Clear previous

        if (!reviewData.chunks || reviewData.chunks.length === 0) {
             reviewContent.innerHTML = '<p>No speech segments found or Stage 1 processing failed before chunking.</p>';
             reviewSection.style.display = 'block';
             submitEditsButton.style.display = 'none';
             enableUI(); // Enable main buttons as there's nothing to review
             inputSection.style.display = 'block'; // Show initial inputs again
             return;
        }

        // Build the review form elements
        reviewData.chunks.forEach(chunk => {
            const chunkDiv = document.createElement('div');
            chunkDiv.className = 'review-chunk';

            // Display Original Transcription (read-only)
            const originalDiv = document.createElement('div');
            originalDiv.className = 'transcription-original';
            originalDiv.innerHTML = `
                <strong>Original Transcription:</strong>
                <p>${chunk.transcribed_text || '(Transcription failed or empty)'}</p>
                <small>Status: ${chunk.transcription_status || 'N/A'}</small>
            `;

            // Editable Translated Text Area
            const translatedLabel = document.createElement('label');
            translatedLabel.htmlFor = `editedTranslatedText_${chunk.index}`;
            translatedLabel.innerHTML = `<strong>Translated Text (Edit Below):</strong>`;

            const translatedStatus = document.createElement('small');
            translatedStatus.textContent = `Status: ${chunk.translation_status || 'N/A'}`;

            const translatedTextarea = document.createElement('textarea');
            translatedTextarea.id = `editedTranslatedText_${chunk.index}`;
            translatedTextarea.dataset.chunkIndex = chunk.index; // Store index
            translatedTextarea.rows = 4;
            translatedTextarea.value = chunk.translated_text || ''; // Pre-fill

            // Download Link for Original Audio Chunk
            const downloadLink = document.createElement('a');
            downloadLink.href = `/serve-chunk/${reviewData.job_id}/${chunk.original_audio_chunk}`;
            downloadLink.target = '_blank';
            downloadLink.download = chunk.original_audio_chunk;
            downloadLink.textContent = `Listen to Original Chunk ${chunk.index + 1}`;
            downloadLink.title = `Download ${chunk.original_audio_chunk}`;

            const separator = document.createElement('hr');

            // Append elements
            chunkDiv.appendChild(originalDiv);
            chunkDiv.appendChild(separator);
            chunkDiv.appendChild(translatedLabel);
            chunkDiv.appendChild(translatedStatus);
            chunkDiv.appendChild(translatedTextarea);
            chunkDiv.appendChild(downloadLink);
            reviewContent.appendChild(chunkDiv);
        });

        inputSection.style.display = 'none'; // Hide the initial upload/url section
        reviewSection.style.display = 'block'; // Show the review section
        submitEditsButton.style.display = 'block'; // Show the submit button
        progressIndicator.style.display = 'none'; // Ensure progress is hidden
        if(submitEditsButton) submitEditsButton.disabled = false; // Ensure submit is enabled
    }

     // --- Hide the Review UI ---
     function hideReviewUI() {
          reviewSection.style.display = 'none';
          reviewContent.innerHTML = '';
          currentJobIdInput.value = '';
     }

    // --- Handle Submission of Edited TRANSLATED Text (Final Stage) ---
    function handleReviewSubmission() {
        if (isProcessingStage1 || isProcessingFinalStage) return;
        isProcessingFinalStage = true; // Use flag for final stage
        disableUIBeforeProcessing();
        setFeedback('Starting Final Stage (TTS & Merging)...', 'info');
        progressStep.textContent = 'Generating Final Video... This may take a while.';
        progressIndicator.style.display = 'flex'; // Show progress

        const jobId = currentJobIdInput.value;
        const editedTranslatedTexts = {}; // Object to hold { "index": "edited text", ... }
        const textAreas = reviewContent.querySelectorAll('textarea[data-chunk-index]');
        textAreas.forEach(ta => {
             editedTranslatedTexts[ta.dataset.chunkIndex] = ta.value; // Use index as key
        });

        const selectedVoice = document.querySelector('input[name="ttsVoice"]:checked').value || 'female';

        // Call the RENAMED final stage endpoint
        fetch('/process-final-stage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                 job_id: jobId,
                 edited_translated_texts: editedTranslatedTexts, // Send edited translated texts
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
             enableUI(); // Re-enable everything for a new job
        })
        .catch(error => {
             console.error('Final Stage Fetch Error:', error);
             setFeedback(`Final Stage Failed: ${error.message}`, 'error');
             // Keep review UI open on failure, but enable submit button
             inputSection.style.display = 'none'; // Keep initial hidden
             reviewSection.style.display = 'block';
             if(submitEditsButton) submitEditsButton.disabled = false;
             // Keep other buttons disabled? Or enable all? Let's enable all for simplicity.
             enableMainInputButtons();
        })
        .finally(() => {
             isProcessingFinalStage = false; // Use renamed flag
             progressIndicator.style.display = 'none';
             progressStep.textContent = '';
             // Reset inputs after completion/failure
             if(videoFileInput) videoFileInput.value = '';
             if(fileFeedback) fileFeedback.textContent = 'No file selected.';
             if(youtubeUrlInput) youtubeUrlInput.value = '';
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
            link.textContent = `Download/View ${filename}`; // Updated text
            link.target = '_blank';
            link.style.display = 'block';
            link.style.marginTop = '10px';
            mainFeedbackArea.appendChild(link);
        } catch (e) {
            console.error("Error adding download link:", e);
            mainFeedbackArea.innerHTML += `<p style="color: red;">Error adding download link for ${filename}.</p>`;
        }
     }

    function disableUIBeforeProcessing() {
        disableMainInputButtons();
        if(submitEditsButton) submitEditsButton.disabled = true;
        progressIndicator.style.display = 'flex'; // Show progress
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
        // Submit button is handled separately based on review state
        if(submitEditsButton) submitEditsButton.disabled = (reviewSection.style.display === 'none');
    }

    function enableMainInputButtons() {
        if(uploadButton) uploadButton.disabled = false;
        if(processUrlButton) processUrlButton.disabled = false;
        if(videoFileInput) videoFileInput.disabled = false;
        if(youtubeUrlInput) youtubeUrlInput.disabled = false;
         const voiceRadios = voiceOptionsContainer.querySelectorAll('input[type="radio"]');
         voiceRadios.forEach(radio => radio.disabled = false);
    }

});
// --- END OF script.js ---