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
    if (conversationActive) {
      if (speaking || busy) await autoInterruptAndListen();
      return;
    }

    try {
      conversationActive = true;
      await ensureSession();
      await resumeAudio();
      await beginListening(false);
    } catch (error) {
      console.error("[MITRA] start failed", error);
      resetSessionState("Mic issue", error.message || "Voice session start nahi hua.", "error");
    }
  }

  async function beginListening(fromBargeIn) {
    if (!conversationActive || listening || busy || speaking) return;
    await ensureSession();
    await resumeAudio();

    listening = true;
    heardVoice = false;
    turnStartedAt = Date.now();
    lastVoiceAt = 0;
    bargeStartedAt = 0;
    sendSignal({ type: "turn.start" });
    setMode("listening", "Listening", fromBargeIn ? "Haan bolo, MITRA ruk gaya." : "Seedha bolna shuru karo, MITRA sun raha hai.");
    startIdleRefresh();
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

      const canBargeIn = conversationActive && speaking && now - speakingStartedAt >= BARGE_IN_GRACE_MS;
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
    if (payload.type === "transcript.final") {
      addTranscript("user", payload.text);
      setMode("thinking", "Thinking", "MITRA ne suna. Ab jawab bana raha hai.");
      return;
    }
    if (payload.type === "assistant.final") {
      addTranscript("mitra", payload.text);
      setMode("thinking", "Voice ready", "MITRA ab bolne wala hai.");
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
