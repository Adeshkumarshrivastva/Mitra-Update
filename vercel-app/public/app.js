/* MITRA in the browser: no server keeps a connection open. The browser listens (speech recognition), asks /api/chat
   for the reply, and speaks it (speech synthesis). Works best in Chrome or Edge. */
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
  const callModal = document.getElementById("callModal");
  const callModalText = document.getElementById("callModalText");
  const callModalTimer = document.getElementById("callModalTimer");
  const callModalActions = document.getElementById("callModalActions");
  const callWaitActions = document.getElementById("callWaitActions");
  const callDialActions = document.getElementById("callDialActions");
  const callDialLink = document.getElementById("callDialLink");
  const callDialNumber = document.getElementById("callDialNumber");
  const callDialClose = document.getElementById("callDialClose");

  const IDLE_NUDGE_MS = 75000;
  const MAX_IDLE_NUDGES = 3;
  const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;

  const usageStartedAt = Date.now();
  let conversationActive = false;
  let listening = false;
  let busy = false;
  let speaking = false;
  let paused = false;
  let recognition = null;
  let speakToken = 0;
  let history = [];
  let convoState = { answered: [], mindcheckDone: false, deferred: false };
  let lastActivity = Date.now();
  let idleNudges = 0;
  let idleTimer = null;

  function setMode(mode, status, hint) {
    document.body.dataset.mode = mode;
    statusText.textContent = status;
    hintText.textContent = hint;
    safetyState.textContent =
      mode === "error" ? "Issue" :
      mode === "speaking" ? "Reply" :
      mode === "listening" ? "Listening" :
      mode === "thinking" ? "Thinking" :
      "Ready";
  }

  async function loadProfile() {
    try {
      const response = await fetch("/api/me", { cache: "no-store" });
      const payload = await response.json();
      if (!payload.profile) {
        window.location.href = "/login";
        return;
      }
      profileLine.textContent = `${payload.profile.name || "Saathi"} - ${payload.profile.route || "Highway"}`;
    } catch {
      setMode("error", "Connection issue", "Internet check karo aur page dobara kholo.");
    }
  }

  // ---- speaking ---------------------------------------------------------------------------------------------------

  function hindiVoice() {
    const voices = synth ? synth.getVoices() : [];
    return voices.find((v) => /^hi[-_]?IN/i.test(v.lang) && /female|google|lekha|swara/i.test(v.name))
      || voices.find((v) => /^hi/i.test(v.lang))
      || null;
  }

  // Long text is spoken sentence by sentence: Chrome silently cuts one long utterance after about 15 seconds.
  function speak(text) {
    return new Promise((resolve) => {
      if (!synth) { resolve(); return; }
      const token = ++speakToken;
      synth.cancel();
      const parts = String(text).match(/[^।.!?]+[।.!?]?/g) || [String(text)];
      const chunks = parts.map((p) => p.trim()).filter(Boolean);
      let index = 0;
      const next = () => {
        if (token !== speakToken) { resolve(); return; }
        if (index >= chunks.length) { resolve(); return; }
        const piece = chunks[index++];
        const utterance = new SpeechSynthesisUtterance(piece);
        utterance.lang = "hi-IN";
        const voice = hindiVoice();
        if (voice) utterance.voice = voice;
        utterance.rate = 0.95;
        let finished = false;
        const done = () => { if (finished) return; finished = true; window.clearTimeout(guard); next(); };
        const guard = window.setTimeout(done, 4000 + piece.length * 160);
        utterance.onend = done;
        utterance.onerror = done;
        synth.speak(utterance);
      };
      next();
    });
  }

  function stopSpeaking() {
    speakToken += 1;
    if (synth) synth.cancel();
  }

  async function say(text) {
    addTranscript("mitra", text);
    speaking = true;
    busy = false;
    setMode("speaking", "Speaking", "Beech me bolna ho to mic tap karo, MITRA ruk jayega.");
    await speak(text);
    speaking = false;
    lastActivity = Date.now();
    if (paused || !conversationActive) return;
    setMode("listening", "Listening", "Bolo bhai, MITRA sun raha hai.");
    window.setTimeout(beginListening, 150);
  }

  // ---- listening --------------------------------------------------------------------------------------------------

  function beginListening() {
    if (!conversationActive || listening || busy || speaking || paused) return;
    listening = true;
    const current = new SpeechRecognitionApi();
    let heard = "";
    current.lang = "hi-IN";
    current.continuous = false;
    current.interimResults = false;
    current.maxAlternatives = 1;
    current.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (event.results[i].isFinal) heard += ` ${event.results[i][0].transcript}`;
      }
    };
    current.onerror = (event) => {
      const fatal = {
        "not-allowed": "Mic ya speech recognition ki permission allow karo.",
        "service-not-allowed": "Browser ne speech recognition allow nahi kiya.",
        "audio-capture": "Mic nahi mila. Mic check karo.",
        network: "Speech recognition ke liye internet chahiye.",
        "language-not-supported": "Is browser me Hindi speech recognition nahi hai.",
      }[event.error];
      if (fatal) resetSession("Mic issue", fatal, "error");
    };
    current.onend = () => {
      if (recognition !== current) return;
      recognition = null;
      if (!listening) return;
      listening = false;
      const text = heard.trim();
      if (!text) {
        if (conversationActive && !paused) window.setTimeout(beginListening, 250);
        return;
      }
      handleUserText(text);
    };
    recognition = current;
    try {
      current.start();
      setMode("listening", "Listening", "Seedha bolna shuru karo, MITRA sun raha hai.");
    } catch {
      listening = false;
      recognition = null;
    }
  }

  function abortRecognition() {
    const current = recognition;
    recognition = null;
    listening = false;
    if (current) current.abort();
  }

  // ---- talking to /api/chat ---------------------------------------------------------------------------------------

  async function chat(payload) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, history, state: convoState }),
    });
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("login");
    }
    return response.json();
  }

  function applyReply(data) {
    if (data.state) convoState = data.state;
    if (Array.isArray(data.append)) history = history.concat(data.append).slice(-30);
    lastActivity = Date.now();
    if (data.helpline && data.number) showDialer(data.number, data.tel);
  }

  async function handleUserText(text) {
    busy = true;
    idleNudges = 0;
    addTranscript("user", text);
    setMode("thinking", "Thinking", "MITRA ne suna. Ab jawab bana rahi hai.");
    try {
      const data = await chat({ text });
      if (!data.ok && !data.text) throw new Error(data.error || "chat");
      if (data.ok) applyReply(data);
      await say(data.text);
    } catch (error) {
      if (error.message === "login") return;
      await say("अरे भैया, अभी नेटवर्क में थोड़ी दिक्कत आ गई। एक बार फिर से बोलिए, मैं यहीं हूँ।");
    }
  }

  // Called by mindcheck.js once the report is shown: MITRA explains the result (and shows the helpline if it is serious).
  window.mitraDeliverMindcheck = async (result) => {
    conversationActive = true;
    paused = false;
    unlockSpeech();
    busy = true;
    setMode("thinking", "Thinking", "MITRA aapki report dekh rahi hai.");
    try {
      const data = await chat({ mindcheck: result });
      if (!data.ok) throw new Error(data.error || "chat");
      applyReply(data);
      await say(data.text);
    } catch (error) {
      if (error.message === "login") return;
      await say("भैया, आपका माइंड चेक पूरा हो गया है। आप चाहें तो मुझसे कुछ भी पूछ सकते हैं।");
    }
  };

  async function nudge() {
    if (!conversationActive || paused || busy || speaking) return;
    busy = true;
    abortRecognition();
    try {
      const data = await chat({ idle: idleNudges });
      idleNudges += 1;
      if (data.ok) applyReply(data);
      await say(data.text || "भैया, सब ठीक तो है ना?");
    } catch {
      busy = false;
      beginListening();
    }
  }

  function startIdleWatch() {
    if (idleTimer) return;
    idleTimer = window.setInterval(() => {
      const quiet = Date.now() - lastActivity >= IDLE_NUDGE_MS;
      if (quiet && idleNudges < MAX_IDLE_NUDGES && history.length > 0) nudge();
    }, 5000);
  }

  // ---- helpline popup ---------------------------------------------------------------------------------------------

  function showDialer(number, tel) {
    paused = true;
    busy = false;
    abortRecognition();
    callDialLink.href = `tel:${String(tel || number).replace(/[^\d+]/g, "")}`;
    callDialNumber.textContent = number;
    callModalText.textContent = "Doctor se baat karne ke liye is helpline number par call karein";
    callModalTimer.hidden = true;
    callModalActions.hidden = true;
    callWaitActions.hidden = true;
    callDialActions.hidden = false;
    callModal.hidden = false;
  }

  function hideCallModal() {
    callModal.hidden = true;
  }

  // ---- session ----------------------------------------------------------------------------------------------------

  // Mobile browsers only allow speech that starts from a tap; a silent utterance on the first tap unlocks it.
  function unlockSpeech() {
    if (!synth) return;
    try { synth.speak(new SpeechSynthesisUtterance(" ")); } catch { /* optional */ }
  }

  function startConversation() {
    unlockSpeech();
    if (paused) {
      paused = false;
      hideCallModal();
    }
    if (speaking) {
      stopSpeaking();
      speaking = false;
    } else if (busy) {
      return;
    }
    conversationActive = true;
    startIdleWatch();
    lastActivity = Date.now();
    beginListening();
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

  function resetSession(status = "Tap to start", hint = "Mic tap karo jab baat karni ho.", mode = "idle") {
    abortRecognition();
    stopSpeaking();
    conversationActive = false;
    busy = false;
    speaking = false;
    paused = false;
    hideCallModal();
    setMode(mode, status, hint);
  }

  function endSession() {
    resetSession("Tap to start", "Safar mode band. Mic tap karke dobara start karo.");
  }

  async function logout() {
    endSession();
    try { await fetch("/api/logout", { method: "POST" }); } catch { /* leaving anyway */ }
    window.location.href = "/login";
  }

  function updateDuration() {
    const elapsed = Math.max(0, Math.floor((Date.now() - usageStartedAt) / 1000));
    durationText.textContent = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  }

  clearTranscriptButton.addEventListener("click", () => {
    transcriptList.innerHTML = '<p class="empty-transcript">Abhi tak koi baat nahi hui.</p>';
  });
  logoutButton.addEventListener("click", logout);
  endButton.addEventListener("click", endSession);
  callDialClose.addEventListener("click", () => {
    hideCallModal();
    setMode("idle", "Paused", "Baat karni ho to mic tap karo.");
  });
  callDialLink.addEventListener("click", () => window.setTimeout(hideCallModal, 800));
  micButton.addEventListener("click", startConversation);

  if (synth) synth.getVoices();
  if (!SpeechRecognitionApi) {
    setMode("error", "Browser not supported", "Speech recognition ke liye latest Chrome ya Edge use karo.");
  } else {
    setMode("idle", "Tap to start", "Ek baar tap karo, phir direct baat chalu.");
  }
  window.setInterval(updateDuration, 1000);
  updateDuration();
  loadProfile();
})();
