(() => {
  const micButton = document.getElementById("micButton");
  const statusText = document.getElementById("statusText");
  const hintText = document.getElementById("hintText");
  const remoteAudio = document.getElementById("remoteAudio");
  const CAPTURE_MS = 5500;

  let ws = null;
  let pc = null;
  let localStream = null;
  let captureTimer = null;
  let active = false;

  function setMode(mode, status, hint) {
    document.body.dataset.mode = mode;
    statusText.textContent = status;
    hintText.textContent = hint;
    console.debug("[MITRA]", mode, status, hint);
  }

  function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/session`;
  }

  function waitForIceGathering(peer) {
    if (peer.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const timeout = window.setTimeout(resolve, 3000);
      peer.addEventListener("icegatheringstatechange", () => {
        if (peer.iceGatheringState === "complete") {
          window.clearTimeout(timeout);
          resolve();
        }
      });
    });
  }

  function sendSignal(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(payload));
  }

  async function startTurn() {
    if (active) {
      stopTurn("Tap to speak", "Stopped. Tap again when you are ready.");
      return;
    }

    active = true;
    setMode("connecting", "Connecting", "Allow microphone access when asked.");

    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      ws = new WebSocket(websocketUrl());
      ws.addEventListener("message", handleSignalMessage);
      ws.addEventListener("close", () => {
        if (active) stopTurn("Tap to speak", "Session closed.");
      });
      ws.addEventListener("error", () => {
        setMode("error", "Connection issue", "Check the MITRA server terminal.");
      });

      await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
      });

      pc = new RTCPeerConnection();
      pc.addEventListener("track", (event) => {
        if (event.streams[0]) {
          remoteAudio.srcObject = event.streams[0];
          remoteAudio.play().catch((error) => console.debug("[MITRA] audio play", error));
        }
      });
      pc.addEventListener("icecandidate", (event) => {
        sendSignal({ type: "ice", candidate: event.candidate });
      });
      pc.addEventListener("connectionstatechange", () => {
        console.debug("[MITRA] pc state", pc.connectionState);
      });

      for (const track of localStream.getAudioTracks()) {
        pc.addTrack(track, localStream);
      }

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      sendSignal({ type: "offer", sdp: pc.localDescription.sdp });

      setMode("listening", "Listening", "Speak naturally. MITRA will answer after this turn.");
      captureTimer = window.setTimeout(stopMicrophoneOnly, CAPTURE_MS);
    } catch (error) {
      console.error("[MITRA] start failed", error);
      stopTurn("Mic issue", error.message || "Could not start the voice session.", "error");
    }
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
      return;
    }
    if (payload.type === "transcript.final") {
      setMode("thinking", "Thinking", "MITRA heard you and is preparing a reply.");
      return;
    }
    if (payload.type === "assistant.final") {
      setMode("speaking", "Speaking", "Listen to MITRA.");
      return;
    }
    if (payload.type === "error") {
      stopTurn("MITRA issue", payload.message || "The voice pipeline stopped.", "error");
      return;
    }
    if (payload.type === "closed") {
      window.setTimeout(() => stopTurn("Tap to speak", "Tap again for the next turn."), 700);
    }
  }

  function stopMicrophoneOnly() {
    if (captureTimer) window.clearTimeout(captureTimer);
    captureTimer = null;
    if (localStream) {
      for (const track of localStream.getTracks()) track.stop();
    }
    localStream = null;
    if (active) setMode("thinking", "Thinking", "Sending your voice to MITRA.");
  }

  function stopTurn(status = "Tap to speak", hint = "Tap the mic when you are ready.", mode = "idle") {
    if (captureTimer) window.clearTimeout(captureTimer);
    captureTimer = null;
    active = false;

    if (localStream) {
      for (const track of localStream.getTracks()) track.stop();
      localStream = null;
    }
    if (pc) {
      pc.close();
      pc = null;
    }
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    ws = null;
    setMode(mode, status, hint);
  }

  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection || !window.WebSocket) {
    setMode("error", "Browser not supported", "Use a current Chrome or Edge browser.");
  } else {
    setMode("idle", "Tap to speak", "MITRA will listen for a short turn and reply by voice.");
  }

  micButton.addEventListener("click", startTurn);
})();
