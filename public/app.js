(() => {
  const assistant = document.querySelector(".assistant");
  const micButton = document.getElementById("micButton");
  const stopButton = document.getElementById("stopButton");
  const statusText = document.getElementById("statusText");
  const hintText = document.getElementById("hintText");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  let recognition = null;
  let active = false;
  let listening = false;
  let busy = false;
  let speaking = false;
  let agentReady = false;
  let speechTimer = null;
  let speechRun = 0;

  function log(message, data) {
    if (data === undefined) console.debug(`[MITRA] ${message}`);
    else console.debug(`[MITRA] ${message}`, data);
  }

  function setMode(mode, status, hint) {
    assistant.className = `assistant ${mode}`;
    statusText.textContent = status;
    if (hint !== undefined) hintText.textContent = hint;
    log(`mode=${mode}`, { status, hint });
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = { ok: false, error: `HTTP ${response.status}` };
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  async function checkMitra() {
    agentReady = false;
    busy = true;
    setMode("thinking", "Checking MITRA", "Verifying the configured agent before starting voice.");
    try {
      await requestJson("/api/check-turn");
      agentReady = true;
      setMode("idle", "Tap and speak", "MITRA is ready. Speak naturally in Hindi, Hinglish, or English.");
    } catch (error) {
      setMode("error", "MITRA issue", error.message || "The configured agent did not answer.");
      log("startup check failed", error.message);
    } finally {
      busy = false;
    }
  }

  function setupRecognition() {
    if (!SpeechRecognition) {
      setMode("error", "Browser not supported", "Use Chrome or Edge for microphone speech recognition.");
      return false;
    }
    if (recognition) return true;

    recognition = new SpeechRecognition();
    recognition.lang = "hi-IN";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.addEventListener("start", () => {
      listening = true;
      setMode("listening", "Listening", "Speak now.");
    });

    recognition.addEventListener("result", (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join(" ")
        .trim();
      log("speech transcript", transcript);
      if (transcript) {
        stopListening();
        sendTurn(transcript);
      }
    });

    recognition.addEventListener("end", () => {
      listening = false;
      log("recognition end", { active, busy, speaking });
      if (active && !busy && !speaking) {
        setMode("idle", "Tap and speak", "Tap the mic again for the next turn.");
        active = false;
      }
    });

    recognition.addEventListener("error", (event) => {
      listening = false;
      busy = false;
      active = false;
      const message = event.error === "not-allowed"
        ? "Microphone blocked"
        : event.error === "no-speech"
          ? "No speech heard"
          : "Mic issue";
      const hint = event.error === "not-allowed"
        ? "Allow microphone access in the browser and try again."
        : "Tap the mic and speak again.";
      setMode("error", message, hint);
      log("recognition error", event.error);
    });

    return true;
  }

  function startListening() {
    if (busy || speaking) return;
    if (!agentReady) {
      checkMitra();
      return;
    }
    if (!setupRecognition()) return;
    active = true;
    try {
      recognition.start();
    } catch (error) {
      log("recognition start failed", error.message);
      setMode("error", "Mic issue", "Tap again in a moment.");
    }
  }

  function stopListening() {
    if (!recognition || !listening) return;
    try {
      recognition.stop();
    } catch {
      listening = false;
    }
  }

  async function sendTurn(text) {
    busy = true;
    active = true;
    setMode("thinking", "Thinking", "MITRA is preparing a reply.");
    log("turn send", text);
    try {
      const result = await requestJson("/api/turn", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      log("turn result", result);
      await speak(result.reply);
    } catch (error) {
      busy = false;
      active = false;
      setMode("error", "MITRA issue", error.message || "Could not get a reply.");
      log("turn failed", error.message);
    }
  }

  function speak(text) {
    const reply = String(text || "").trim();
    busy = false;
    if (!reply) {
      setMode("error", "No reply", "MITRA returned an empty response.");
      return Promise.resolve();
    }

    if (!("speechSynthesis" in window)) {
      setMode("idle", "Reply received", "Speech playback is not available in this browser.");
      return Promise.resolve();
    }

    speaking = true;
    setMode("speaking", "Speaking", "Listen to MITRA.");
    window.speechSynthesis.cancel();
    if (speechTimer) window.clearTimeout(speechTimer);
    const thisRun = ++speechRun;

    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(reply);
      utterance.lang = "hi-IN";
      utterance.rate = 0.96;
      utterance.pitch = 1;

      const voices = window.speechSynthesis.getVoices();
      const voice = voices.find((item) => item.lang === "hi-IN")
        || voices.find((item) => item.lang.toLowerCase().startsWith("hi"))
        || voices.find((item) => item.lang.toLowerCase().includes("in"));
      if (voice) utterance.voice = voice;

      const finish = (label) => {
        if (thisRun !== speechRun) return;
        if (speechTimer) window.clearTimeout(speechTimer);
        speaking = false;
        active = false;
        setMode("idle", "Tap and speak", "Tap the mic for the next turn.");
        log(`speech ${label}`);
        resolve();
      };

      utterance.addEventListener("end", () => finish("end"));
      utterance.addEventListener("error", (event) => {
        log("speech error", event.error);
        finish("error");
      });

      speechTimer = window.setTimeout(() => finish("watchdog"), Math.min(Math.max(reply.length * 85, 4000), 26000));
      window.speechSynthesis.speak(utterance);
    });
  }

  function stopAll() {
    active = false;
    busy = false;
    speaking = false;
    stopListening();
    if (speechTimer) window.clearTimeout(speechTimer);
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setMode("idle", "Tap and speak", "Tap the mic when you are ready.");
  }

  micButton.addEventListener("click", () => {
    if (listening || busy || speaking) {
      stopAll();
    } else {
      startListening();
    }
  });

  stopButton.addEventListener("click", stopAll);
  checkMitra();
})();
