(() => {
  const micButton = document.getElementById("micButton");
  const endButton = document.getElementById("endButton");
  const logoutButton = document.getElementById("logoutButton");
  const clearTranscriptButton = document.getElementById("clearTranscriptButton");
  const statusText = document.getElementById("statusText");
  const hintText = document.getElementById("hintText");
  const profileLine = document.getElementById("profileLine");
  const safetyState = document.getElementById("safetyState");
  const durationText = document.getElementById("durationText");
  const transcriptList = document.getElementById("transcriptList");
  const remoteAudio = document.getElementById("remoteAudio");
  const callModal = document.getElementById("callModal");
  const callModalText = document.getElementById("callModalText");
  const callModalTimer = document.getElementById("callModalTimer");
  const callModalActions = document.getElementById("callModalActions");
  const callWaitActions = document.getElementById("callWaitActions");
  const callYesButton = document.getElementById("callYesButton");
  const callNoButton = document.getElementById("callNoButton");
  const callArrivedButton = document.getElementById("callArrivedButton");
  const callDialActions = document.getElementById("callDialActions");
  const callDialLink = document.getElementById("callDialLink");
  const callDialNumber = document.getElementById("callDialNumber");
  const callDialClose = document.getElementById("callDialClose");
  const callPrefGroup = document.getElementById("callPrefGroup");
  const callPrefRadios = Array.from(document.querySelectorAll('input[name="callPref"]'));

  const MIN_TURN_MS = 1000;
  const MAX_TURN_MS = 12000;
  const SILENCE_MS = 820;
  const IDLE_REFRESH_MS = 8000;
  const VOLUME_THRESHOLD = 0.019;
  const BARGE_IN_VOLUME_THRESHOLD = 0.075;
  const BARGE_IN_MS = 650;
  const BARGE_IN_GRACE_MS = 900;

  let ws = null;
  let pc = null;
  let localStream = null;
  let audioContext = null;
  let analyser = null;
  let analyserData = null;
  let monitorTimer = null;
  let maxCaptureTimer = null;
  let idleRefreshTimer = null;
  let usageStartedAt = Date.now();
  let conversationActive = false;
  let listening = false;
  let busy = false;
  let speaking = false;
  let connected = false;
  let pendingAnswerResolve = null;
  let heardVoice = false;
  let turnStartedAt = 0;
  let lastVoiceAt = 0;
  let bargeStartedAt = 0;
  let speakingStartedAt = 0;
  let autoStarting = false;
  let paused = false;
  let callDeadline = 0;
  let callTimerInterval = null;

  // STT_PROVIDER=browser: Chrome/Edge recognize speech and only the text goes to the server.
  const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
  let browserStt = false;
  let recognition = null;

  function setMode(mode, status, hint) {
    document.body.dataset.mode = mode;
    statusText.textContent = status;
    hintText.textContent = hint;
    safetyState.textContent =
      mode === "error" ? "Issue" :
      mode === "speaking" ? "Reply" :
      mode === "listening" ? "Listening" :
      mode === "thinking" ? "Thinking" :
      connected ? "Ready" : "Standby";
    console.debug("[MITRA]", mode, status, hint);
  }

  function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/session`;
  }

  function sendSignal(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(payload));
  }

  async function loadProfile() {
    const response = await fetch("/api/me", { cache: "no-store" });
    const payload = await response.json();
    if (!payload.profile) {
      window.location.href = "/login";
      return;
    }
    const name = payload.profile.name || "Saathi";
    const route = payload.profile.route || "Highway";
    profileLine.textContent = `${name} - ${route}`;
    browserStt = payload.stt_provider === "browser";
    if (browserStt && !SpeechRecognitionApi) {
      setMode("error", "Browser not supported", "Speech recognition ke liye latest Chrome ya Edge use karo.");
    }
  }

  async function ensureSession() {
    if (connected && ws?.readyState === WebSocket.OPEN && pc?.connectionState !== "closed") return;

    setMode("connecting", "Connecting", "Mic permission allow karo.");
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    setupAnalyser(localStream);
    startAudioMonitor();

    ws = new WebSocket(websocketUrl());
    ws.addEventListener("message", handleSignalMessage);
    ws.addEventListener("close", () => {
      connected = false;
      if (conversationActive) resetSessionState("Tap to start", "Connection band ho gaya. Dobara start karo.");
    });
    ws.addEventListener("error", () => {
      setMode("error", "Connection issue", "Server terminal me logs dekho.");
    });

    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    });

    pc = new RTCPeerConnection();
    pc.addEventListener("track", (event) => {
      if (event.streams[0]) remoteAudio.srcObject = event.streams[0];
    });
    pc.addEventListener("icecandidate", (event) => {
      sendSignal({ type: "ice", candidate: event.candidate });
    });
    pc.addEventListener("connectionstatechange", () => {
      console.debug("[MITRA] pc state", pc.connectionState);
      if (pc.connectionState === "connected") connected = true;
    });

    for (const track of localStream.getAudioTracks()) {
      pc.addTrack(track, localStream);
    }

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    sendSignal({ type: "offer", sdp: pc.localDescription.sdp });

    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        pendingAnswerResolve = null;
        reject(new Error("WebRTC answer timeout"));
      }, 6000);
      pendingAnswerResolve = () => {
        window.clearTimeout(timeout);
        pendingAnswerResolve = null;
        resolve();
      };
    });
  }

  function setupAnalyser(stream) {
    if (audioContext) return;
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.12;
    source.connect(analyser);
    analyserData = new Uint8Array(analyser.fftSize);
  }

  async function startConversation() {
    if (paused) {
      await resumeFromPause();
      return;
    }
    if (conversationActive) {
      if (speaking || busy) await autoInterruptAndListen();
      return;
    }

    try {
      conversationActive = true;
      await ensureSession();
      sendSignal({ type: "call_preference", value: selectedPreference() });
      lockPreference(true);
      await resumeAudio();
      await beginListening(false);
    } catch (error) {
      console.error("[MITRA] start failed", error);
      resetSessionState("Mic issue", error.message || "Voice session start nahi hua.", "error");
    }
  }

  // Called by mindcheck.js once the report is shown: MITRA speaks the verdict (and calls the doctors if it is bad).
  window.mitraDeliverMindcheck = async (result) => {
    try {
      conversationActive = true;
      await ensureSession();
      sendSignal({ type: "call_preference", value: "ai_agent" });
      lockPreference(true);
      await resumeAudio();
      busy = true;
      sendSignal({ type: "mindcheck.result", ...result });
      setMode("thinking", "Thinking", "MITRA aapki report dekh rahi hai.");
    } catch (error) {
      console.error("[MITRA] mindcheck handoff failed", error);
      resetSessionState("Mic issue", error.message || "Voice session start nahi hua.", "error");
    }
  };

  async function beginListening(fromBargeIn) {
    if (!conversationActive || listening || busy || speaking) return;
    await ensureSession();
    await resumeAudio();

    listening = true;
    heardVoice = false;
    turnStartedAt = Date.now();
    lastVoiceAt = 0;
    bargeStartedAt = 0;
    if (browserStt) {
      startRecognition();
    } else {
      sendSignal({ type: "turn.start" });
    }
    setMode("listening", "Listening", fromBargeIn ? "Haan bolo, MITRA ruk gaya." : "Seedha bolna shuru karo, MITRA sun raha hai.");
    if (!browserStt) startIdleRefresh();
  }

  function startRecognition() {
    abortRecognition();
    const current = new SpeechRecognitionApi();
    let heardText = "";
    current.lang = "hi-IN";
    current.continuous = false;
    current.interimResults = false;
    current.maxAlternatives = 1;
    current.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (event.results[i].isFinal) heardText += ` ${event.results[i][0].transcript}`;
      }
    };
    current.onerror = (event) => {
      console.debug("[MITRA] speech recognition error", event.error);
      const fatal = {
        "not-allowed": "Mic ya speech recognition ki permission allow karo.",
        "service-not-allowed": "Browser ne speech recognition allow nahi kiya.",
        "audio-capture": "Mic nahi mila. Mic check karo.",
        network: "Speech recognition ke liye internet chahiye.",
        "language-not-supported": "Is browser me Hindi speech recognition nahi hai.",
      }[event.error];
      if (fatal) resetSessionState("Mic issue", fatal, "error");
    };
    current.onend = () => {
      if (recognition !== current) return;
      recognition = null;
      if (!listening) return;
      listening = false;
      const text = heardText.trim();
      if (!text) {
        if (conversationActive) window.setTimeout(() => beginListening(false), 250);
        return;
      }
      busy = true;
      sendSignal({ type: "transcript", text });
      setMode("thinking", "Thinking", "MITRA ne suna. Ab jawab bana raha hai.");
    };
    recognition = current;
    current.start();
  }

  function abortRecognition() {
    const current = recognition;
    recognition = null;
    if (current) current.abort();
  }

  async function resumeAudio() {
    if (audioContext?.state === "suspended") await audioContext.resume();
    if (remoteAudio.srcObject) {
      remoteAudio.play().catch((error) => console.debug("[MITRA] audio play", error));
    }
  }

  function startAudioMonitor() {
    if (monitorTimer) return;
    monitorTimer = window.setInterval(() => {
      if (!analyser || !analyserData) return;
      const volume = currentVolume();
      const now = Date.now();

      if (listening) {
        if (browserStt) return;
        if (volume > VOLUME_THRESHOLD) {
          if (!heardVoice) {
            heardVoice = true;
            turnStartedAt = now;
            startMaxCapture();
            clearIdleRefresh();
          }
          lastVoiceAt = now;
        }

        const longEnough = heardVoice && now - turnStartedAt >= MIN_TURN_MS;
        const silentEnough = heardVoice && now - lastVoiceAt >= SILENCE_MS;
        if (longEnough && silentEnough) stopListening("silence");
        return;
      }

      const canBargeIn = !paused && conversationActive && speaking && now - speakingStartedAt >= BARGE_IN_GRACE_MS;
      if (canBargeIn && volume > BARGE_IN_VOLUME_THRESHOLD) {
        if (!bargeStartedAt) bargeStartedAt = now;
        if (!autoStarting && now - bargeStartedAt >= BARGE_IN_MS) autoInterruptAndListen();
      } else {
        bargeStartedAt = 0;
      }
    }, 70);
  }

  function currentVolume() {
    analyser.getByteTimeDomainData(analyserData);
    let sum = 0;
    for (const value of analyserData) {
      const normalized = (value - 128) / 128;
      sum += normalized * normalized;
    }
    return Math.sqrt(sum / analyserData.length);
  }

  function stopAudioMonitor() {
    if (monitorTimer) window.clearInterval(monitorTimer);
    monitorTimer = null;
  }

  function startMaxCapture() {
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = window.setTimeout(() => stopListening("max_duration"), MAX_TURN_MS);
  }

  function startIdleRefresh() {
    clearIdleRefresh();
    idleRefreshTimer = window.setTimeout(() => {
      if (!conversationActive || !listening || heardVoice) return;
      sendSignal({ type: "turn.cancel", reason: "no_speech" });
      listening = false;
      window.setTimeout(() => beginListening(false), 80);
    }, IDLE_REFRESH_MS);
  }

  function clearIdleRefresh() {
    if (idleRefreshTimer) window.clearTimeout(idleRefreshTimer);
    idleRefreshTimer = null;
  }

  function stopListening(reason) {
    if (!listening) return;
    clearIdleRefresh();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;

    listening = false;
    if (!heardVoice) {
      sendSignal({ type: "turn.cancel", reason: "no_speech" });
      if (conversationActive) window.setTimeout(() => beginListening(false), 80);
      return;
    }

    busy = true;
    sendSignal({ type: "turn.stop", reason });
    setMode("thinking", "Thinking", "Voice MITRA ko bhej di.");
  }

  async function autoInterruptAndListen() {
    if (autoStarting) return;
    autoStarting = true;
    sendSignal({ type: "interrupt" });
    remoteAudio.pause();
    speaking = false;
    busy = false;
    listening = false;
    clearIdleRefresh();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;
    await beginListening(true);
    autoStarting = false;
  }

  function selectedPreference() {
    const checked = callPrefRadios.find((radio) => radio.checked);
    return checked ? checked.value : "ai_agent";
  }

  function lockPreference(locked) {
    callPrefRadios.forEach((radio) => { radio.disabled = locked; });
    if (callPrefGroup) callPrefGroup.dataset.locked = locked ? "true" : "false";
  }

  function enterQuietPause(hint) {
    paused = true;
    listening = false;
    busy = false;
    clearIdleRefresh();
    abortRecognition();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;
    setMode("idle", "Paused", hint || "Aap baat kar lijiye. Mic tap karke MITRA ko wapas bulayein.");
  }

  function showCallConfirm(timeoutMs) {
    paused = true;
    listening = false;
    busy = false;
    clearIdleRefresh();
    abortRecognition();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;
    clearCallTimer();

    callDeadline = Date.now() + timeoutMs;
    callModalText.textContent = "Kya aapko call aa gayi?";
    callModalTimer.hidden = true;
    callModalActions.hidden = false;
    callWaitActions.hidden = true;
    callDialActions.hidden = true;
    callModal.hidden = false;
    setMode("speaking", "Call connected", "Neeche batao — call aa gayi?");
  }

  function showDialer(number, tel) {
    paused = true;
    listening = false;
    busy = false;
    clearIdleRefresh();
    abortRecognition();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;
    clearCallTimer();

    callDialLink.href = `tel:${String(tel || number).replace(/[^\d+]/g, "")}`;
    callDialNumber.textContent = number;
    callModalText.textContent = "Doctor se baat karne ke liye is helpline number par call karein";
    callModalTimer.hidden = true;
    callModalActions.hidden = true;
    callWaitActions.hidden = true;
    callDialActions.hidden = false;
    callModal.hidden = false;
    setMode("idle", "Paused", "Number par tap karke call kijiye.");
  }

  function hideCallModal() {
    clearCallTimer();
    callModal.hidden = true;
  }

  function clearCallTimer() {
    if (callTimerInterval) window.clearInterval(callTimerInterval);
    callTimerInterval = null;
  }

  function onCallReceived() {
    hideCallModal();
    sendSignal({ type: "healthcare.confirm", received: true });
    // Stay paused while the driver is on the call. Tap mic to resume later.
    speaking = false;
    busy = false;
    setMode("idle", "Paused", "Call chal rahi hai. Baat karni ho to mic tap karo.");
  }

  function onCallNotArrivedYet() {
    callModalText.textContent = "Thoda rukiye, call aa rahi hai…";
    callModalActions.hidden = true;
    callWaitActions.hidden = false;
    callModalTimer.hidden = false;
    startCallCountdown();
  }

  function startCallCountdown() {
    clearCallTimer();
    updateCallCountdown();
    callTimerInterval = window.setInterval(updateCallCountdown, 250);
  }

  function updateCallCountdown() {
    const remaining = Math.max(0, Math.ceil((callDeadline - Date.now()) / 1000));
    callModalTimer.textContent = `${remaining}s`;
    if (remaining <= 0) onCallTimeout();
  }

  function onCallTimeout() {
    clearCallTimer();
    hideCallModal();
    paused = false;
    busy = true;
    setMode("thinking", "MITRA soch raha hai", "Call nahi aayi, MITRA sambhal raha hai.");
    sendSignal({ type: "healthcare.confirm", received: false });
  }

  async function resumeFromPause() {
    paused = false;
    hideCallModal();
    if (!conversationActive) {
      await startConversation();
      return;
    }
    await beginListening(false);
  }

  async function handleSignalMessage(event) {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    console.debug("[MITRA] signal", payload.type);

    if (payload.type === "answer") {
      await pc.setRemoteDescription({ type: "answer", sdp: payload.sdp });
      connected = true;
      if (pendingAnswerResolve) pendingAnswerResolve();
      return;
    }
    if (payload.type === "turn.empty") {
      busy = false;
      if (conversationActive) window.setTimeout(() => beginListening(false), 120);
      return;
    }
    if (payload.type === "turn.busy") {
      busy = true;
      setMode("thinking", "Thinking", "Ek second bhai, pehle wala jawab aa raha hai.");
      return;
    }
    if (payload.type === "healthcare.call.connecting") {
      setMode("speaking", "Connecting call", "Doctor se call jod rahe hain, thoda rukiye.");
      return;
    }
    if (payload.type === "healthcare.call.queued") {
      const idText = payload.call_id ? ` (${payload.call_id})` : "";
      setMode("speaking", "Call connected", `Healthcare team se call jud gayi${idText}.`);
      return;
    }
    if (payload.type === "healthcare.call.await_confirm") {
      showCallConfirm(payload.timeout_ms || 30000);
      return;
    }
    if (payload.type === "healthcare.call.open_dialer") {
      if (payload.number) showDialer(payload.number, payload.tel);
      return;
    }
    if (payload.type === "healthcare.call.paused") {
      if (!callModal.hidden) return; // dialer popup already handling the pause
      enterQuietPause(payload.hint);
      return;
    }
    if (payload.type === "healthcare.call.doctor_called") {
      setMode("speaking", "Doctor ko call lagi", "Doctors ko call laga di gayi hai, wo aapse sampark karenge.");
      return;
    }
    if (payload.type === "healthcare.call.deferred") {
      setMode("speaking", "Reminder set", "Jab aap kahenge, MITRA doctor se baat karwa degi.");
      return;
    }
    if (payload.type === "healthcare.call.failed") {
      setMode("speaking", "Call issue", "Call abhi jud nahi payi, MITRA dobara koshish karegi.");
      return;
    }
    if (payload.type === "transcript.final") {
      addTranscript("user", payload.text);
      setMode("thinking", "Thinking", "MITRA ne suna. Ab jawab bana raha hai.");
      return;
    }
    if (payload.type === "assistant.final") {
      addTranscript("mitra", payload.text);
      // Streamed replies start speaking before the final text arrives.
      if (!speaking) setMode("thinking", "Voice ready", "MITRA ab bolne wala hai.");
      return;
    }
    if (payload.type === "assistant.audio.started") {
      busy = false;
      speaking = true;
      speakingStartedAt = Date.now();
      await resumeAudio();
      setMode("speaking", "Speaking", "Aap bolenge to MITRA khud ruk jayega.");
      return;
    }
    if (payload.type === "assistant.audio.done") {
      if (paused) {
        speaking = false;
        busy = false;
        speakingStartedAt = 0;
        return;
      }
      if (!listening) {
        busy = false;
        speaking = false;
        speakingStartedAt = 0;
        if (conversationActive) {
          setMode("listening", "Listening", "Bolo bhai, MITRA sun raha hai.");
          window.setTimeout(() => beginListening(false), 120);
        } else {
          setMode("idle", "Tap to start", "Mic tap karo jab baat karni ho.");
        }
      }
      return;
    }
    if (payload.type === "error") {
      resetSessionState("MITRA issue", payload.message || "Voice pipeline ruk gaya.", "error");
      return;
    }
    if (payload.type === "closed") {
      resetSessionState("Tap to start", "Session end ho gaya. Zarurat ho to dobara start karo.");
    }
  }

  function addTranscript(role, text) {
    const clean = String(text || "").trim();
    if (!clean) return;
    const empty = transcriptList.querySelector(".empty-transcript");
    if (empty) empty.remove();

    const bubble = document.createElement("article");
    bubble.className = `bubble ${role}`;
    const label = document.createElement("span");
    label.textContent = role === "user" ? "Aap" : "MITRA";
    const content = document.createElement("p");
    content.textContent = clean;
    bubble.append(label, content);
    transcriptList.appendChild(bubble);
    transcriptList.scrollTop = transcriptList.scrollHeight;
  }

  function endSession() {
    conversationActive = false;
    sendSignal({ type: "end" });
    resetSessionState("Tap to start", "Safar mode band. Mic tap karke dobara start karo.");
  }

  function resetSessionState(status = "Tap to start", hint = "Mic tap karo jab baat karni ho.", mode = "idle") {
    stopAudioMonitor();
    clearIdleRefresh();
    abortRecognition();
    if (maxCaptureTimer) window.clearTimeout(maxCaptureTimer);
    maxCaptureTimer = null;
    conversationActive = false;
    listening = false;
    busy = false;
    speaking = false;
    connected = false;
    pendingAnswerResolve = null;
    autoStarting = false;
    bargeStartedAt = 0;
    speakingStartedAt = 0;
    paused = false;
    hideCallModal();
    lockPreference(false);

    if (localStream) {
      for (const track of localStream.getTracks()) track.stop();
      localStream = null;
    }
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
      analyser = null;
      analyserData = null;
    }
    if (pc) {
      pc.close();
      pc = null;
    }
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    ws = null;
    remoteAudio.pause();
    remoteAudio.srcObject = null;
    setMode(mode, status, hint);
  }

  async function logout() {
    endSession();
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
  }

  function updateDuration() {
    const elapsed = Math.max(0, Math.floor((Date.now() - usageStartedAt) / 1000));
    const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const seconds = String(elapsed % 60).padStart(2, "0");
    durationText.textContent = `${minutes}:${seconds}`;
  }

  clearTranscriptButton.addEventListener("click", () => {
    transcriptList.innerHTML = '<p class="empty-transcript">Abhi tak koi baat nahi hui.</p>';
  });

  logoutButton.addEventListener("click", logout);
  endButton.addEventListener("click", endSession);
  callYesButton.addEventListener("click", onCallReceived);
  callArrivedButton.addEventListener("click", onCallReceived);
  callNoButton.addEventListener("click", onCallNotArrivedYet);
  callDialClose.addEventListener("click", () => {
    hideCallModal();
    setMode("idle", "Paused", "Call karni ho to mic tap karke number dobara mangwa lo.");
  });
  callDialLink.addEventListener("click", () => {
    // Let the tel: navigation proceed, then free the mic button for when they return.
    window.setTimeout(hideCallModal, 800);
  });

  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection || !window.WebSocket) {
    setMode("error", "Browser not supported", "Latest Chrome ya Edge use karo.");
  } else {
    setMode("idle", "Tap to start", "Ek baar tap karo, phir direct baat chalu.");
  }

  micButton.addEventListener("click", startConversation);
  window.setInterval(updateDuration, 1000);
  updateDuration();
  loadProfile();
})();
