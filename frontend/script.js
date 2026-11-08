const recordBtn = document.getElementById("recordBtn");
const playBtn = document.getElementById("playBtn");
const languageSelect = document.getElementById("language");

const statusText = document.getElementById("status");
const transcriptText = document.getElementById("transcript");
const answerText = document.getElementById("answer");

let mediaRecorder;
let audioChunks = [];
let replyAudio = null;
let isRecording = false;

// Start or stop recording
recordBtn.addEventListener("click", async () => {

    if (!isRecording) {
        await startRecording();
    } else {
        stopRecording();
    }

});

// Start microphone recording
async function startRecording() {

    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: true
        });

        audioChunks = [];

        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = async () => {

            const audioBlob = new Blob(audioChunks, {
                type: mediaRecorder.mimeType
            });

            stream.getTracks().forEach(track => track.stop());

            await sendAudioToBackend(audioBlob);
        };

        mediaRecorder.start();

        isRecording = true;

        recordBtn.textContent = "⏹ Stop Recording";
        statusText.textContent = "Listening... Speak your question.";

        transcriptText.textContent = "Listening...";
        answerText.textContent = "Waiting for your question...";

        playBtn.disabled = true;

    } catch (error) {

        statusText.textContent =
            "Microphone access failed. Please allow microphone permission.";

        console.error(error);
    }
}

// Stop microphone recording
function stopRecording() {

    if (mediaRecorder && mediaRecorder.state === "recording") {

        mediaRecorder.stop();

        isRecording = false;

        recordBtn.textContent = "🎤 Start Speaking";
        statusText.textContent = "Processing your question...";
    }
}

// Send recorded audio to CampusSaathi backend
async function sendAudioToBackend(recordedAudio) {

    try {

        statusText.textContent = "Converting audio to WAV...";

        // Convert browser recording to WAV
        const wavAudio = await convertToWav(recordedAudio);

        const formData = new FormData();

        formData.append(
            "audio_file",
            wavAudio,
            "campus_question.wav"
        );

        const language = languageSelect.value;

        statusText.textContent = "Sending question to CampusSaathi...";

        const response = await fetch(
            `http://127.0.0.1:8000/voice-ask?language_code=${encodeURIComponent(language)}`,
            {
                method: "POST",
                body: formData
            }
        );

        if (!response.ok) {
    const error = await response.json().catch(() => ({}));

    throw new Error(
        error.detail || "Voice request failed. Please try again."
    );
 } 

        const data = await response.json();

        transcriptText.textContent = data.transcript;
        answerText.textContent = data.answer;

        // Decode generated WAV audio
        const binary = atob(data.audio_base64);
        const bytes = new Uint8Array(binary.length);

        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }

        const replyBlob = new Blob([bytes], {
            type: data.audio_content_type || "audio/wav"
        });

        if (replyAudio) {
            replyAudio.pause();
            URL.revokeObjectURL(replyAudio.src);
        }

        const audioUrl = URL.createObjectURL(replyBlob);

        replyAudio = new Audio(audioUrl);

        playBtn.disabled = false;

        statusText.textContent = "Answer received successfully!";

    } catch (error) {

        statusText.textContent = "Error: " + error.message;
        console.error(error);

    }
}

// Play the spoken answer
playBtn.addEventListener("click", () => {

    if (replyAudio) {
        replyAudio.play();
    }

});

async function convertToWav(audioBlob) {

    const audioContext = new AudioContext();

    const arrayBuffer = await audioBlob.arrayBuffer();

    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    const numberOfChannels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;

    const length = audioBuffer.length * numberOfChannels * 2;
    const wavBuffer = new ArrayBuffer(44 + length);
    const view = new DataView(wavBuffer);

    function writeString(offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }

    writeString(0, "RIFF");
    view.setUint32(4, 36 + length, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numberOfChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numberOfChannels * 2, true);
    view.setUint16(32, numberOfChannels * 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, length, true);

    let offset = 44;

    for (let i = 0; i < audioBuffer.length; i++) {
        for (let channel = 0; channel < numberOfChannels; channel++) {

            let sample = audioBuffer.getChannelData(channel)[i];

            sample = Math.max(-1, Math.min(1, sample));

            view.setInt16(
                offset,
                sample < 0 ? sample * 32768 : sample * 32767,
                true
            );

            offset += 2;
        }
    }

    await audioContext.close();

    return new Blob([wavBuffer], { type: "audio/wav" });
}