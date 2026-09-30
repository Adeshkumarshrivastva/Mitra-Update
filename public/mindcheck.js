(() => {
  // Mind Check screening (GAD-7 / PHQ-9), behaviour ported from ../Minds-Ai: voice answers, face expression, PDF report,
  // doctors, dashboard. Runs right after login, then hands the result to MITRA. Everything is static for now.
  const MC = window.MC;
  const Report = window.MCReport;
  const { questions, labels, confirmIndices, maxScore } = MC;

  const FACE_API_SRC = "https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js";
  const FACE_WEIGHTS = "https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@master/weights";
  const STORAGE_KEY = "mws-submissions";
  const MAX_VOICE_RETRIES = 3;

  const ui = {
    hi: {
      eyebrow: "पहले एक छोटा सा चेक-इन",
      title: "माइंड चेक",
      intro: "पिछले 2 हफ्तों में ये बातें आपको कितना परेशान करती रहीं? सही या गलत कुछ नहीं, बस जो सच लगे वही चुनिए।",
      anxiety: "चिंता की जाँच (GAD-7, 7 सवाल)",
      depression: "डिप्रेशन की जाँच (PHQ-9, 9 सवाल)",
      consent: "मैं समझता/समझती हूँ कि यह कोई मेडिकल डायग्नोसिस नहीं है। कैमरा सिर्फ चेहरे के भाव पढ़ने के लिए है, कुछ रिकॉर्ड नहीं होता।",
      consentNeeded: "आगे बढ़ने के लिए सहमति ज़रूरी है।",
      question: "सवाल",
      voiceOn: "🔊 आवाज़ चालू",
      voiceOff: "🔇 आवाज़ बंद",
      back: "← पीछे",
      listening: "🎙️ सुन रहा हूँ… बोलिए",
      heard: "आपने कहा: ",
      noMatch: "समझ नहीं आया। ऊपर से कोई विकल्प दबा दीजिए या दोबारा बोलिए।",
      noVoice: "इस ब्राउज़र में आवाज़ से जवाब नहीं चलता। विकल्प दबाइए।",
      confirmPrefix: "आपने कहा ",
      confirmQuestion: "क्या यह सही है? हाँ या नहीं बोलिए।",
      cameraBlocked: "कैमरा नहीं मिला। कोई बात नहीं, जवाब और स्कोर पर इसका असर नहीं है।",
      cameraModel: "एक्सप्रेशन मॉडल लोड नहीं हो सका। आपके जवाब और स्कोर पर इसका असर नहीं है।",
      detecting: "चेहरा पढ़ रहा है",
      tension: "तनाव",
      detailsTitle: "आपकी जानकारी",
      detailsNote: "रिपोर्ट में यह जानकारी लिखी जाएगी।",
      name: "पूरा नाम",
      mobile: "मोबाइल नंबर",
      email: "ईमेल (वैकल्पिक)",
      required: "कृपया नाम और सही मोबाइल नंबर भरिए।",
      invalidEmail: "ईमेल सही नहीं है।",
      seeResult: "मेरा नतीजा देखें",
      reportTitle: "आपकी रिपोर्ट",
      reportHeading: "मानसिक स्वास्थ्य स्क्रीनिंग रिपोर्ट",
      date: "तारीख",
      instrument: "जाँच",
      refNo: "रेफ़रेंस",
      totalScore: "कुल स्कोर",
      scaleTitle: "स्कोर की सीमाएँ और उनका मतलब",
      scoreHere: "आपका स्कोर",
      colRange: "स्कोर",
      colCategory: "श्रेणी",
      colMeaning: "आमतौर पर मतलब",
      severity: "गंभीरता का पैमाना",
      yourScore: "<आपका स्कोर>",
      tips: "आपके लिए सुझाव",
      expression: "चेहरे के भाव (पूरे सेशन का औसत)",
      immediate: "तुरंत मदद",
      immediateNote: "आपने खुद को नुकसान पहुँचाने के विचार बताए हैं। यह गंभीर है, कृपया अभी किसी से बात कीजिए:",
      doctors: "हमारे विशेषज्ञ",
      book: "अपॉइंटमेंट लें",
      mitraCalls: "आपका नतीजा गंभीर है। MITRA आपके लिए डॉक्टर को कॉल लगाएगी।",
      report: "⬇ PDF रिपोर्ट",
      certificate: "⬇ सर्टिफिकेट",
      mitra: "MITRA से बात करें",
      dashboard: "डैशबोर्ड",
      retake: "दोबारा जाँच करें",
      // note: "यह स्क्रीनिंग है, मेडिकल डायग्नोसिस नहीं।",
      lang: "English",
      repeat: "दोबारा सुनाएं",
      keys: "कीबोर्ड: 1-4 से जवाब, ← पीछे",
      liveTitle: "लाइव चेहरे के भाव",
      faceWait: "कैमरा शुरू हो रहा है…",
      faceOk: "चेहरा दिख रहा है",
      faceNone: "चेहरा नहीं दिख रहा। कैमरे के सामने आइए और रोशनी में बैठिए।",
      recorded: "जवाब दर्ज ✓",
      timeline: "हर सवाल पर आपके चेहरे के भाव",
      insightTitle: "चेहरा और जवाब, दोनों का मेल",
      insightMismatch: "आपके जवाब हल्के हैं, पर जवाब देते समय चेहरे पर तनाव दिखा। हो सकता है आप जितना बता रहे हैं, अंदर उससे ज़्यादा चल रहा हो। किसी अपने से या हमारे विशेषज्ञ से एक बार बात कीजिए।",
      insightConfirm: "आपके जवाब और आपके चेहरे के भाव, दोनों तनाव की तरफ इशारा कर रहे हैं। देर मत कीजिए, विशेषज्ञ से बात कीजिए।",
      insightCalm: "जवाब देते समय चेहरा शांत रहा, पर आपके जवाब गंभीर हैं। हम जवाबों को ही सबसे ज़्यादा अहमियत देते हैं, कृपया विशेषज्ञ से बात कीजिए।",
      insightOk: "आपके जवाब और चेहरे के भाव आपस में मेल खाते हैं।",
      tierTitle: "प्राथमिकता",
      tierUrgent: "तुरंत मदद ज़रूरी",
      tierElevated: "ध्यान देने लायक",
      tierNormal: "सामान्य",
      rushed: "आपने सारे जवाब बहुत जल्दी और एक जैसे दिए। शायद ध्यान से नहीं पढ़ा। सही नतीजे के लिए एक बार आराम से दोबारा जाँच कर लीजिए।",
      trendTitle: "पिछली जाँच से तुलना",
      trendFirst: "यह आपकी पहली जाँच है। आगे इसी से तुलना होगी।",
      trendBetter: "पिछली बार {prev} था, अब {now}। पहले से बेहतर है, ऐसे ही ध्यान रखिए।",
      trendWorse: "पिछली बार {prev} था, अब {now}। पहले से थोड़ा बिगड़ा है, इसे हल्के में मत लीजिए।",
      trendSame: "पिछली बार {prev} था, अब {now}। लगभग वैसा ही है।",
      safetyTitle: "ड्राइविंग के लिए ज़रूरी सलाह",
      safetyDrowsy: "आपके जवाब नींद, थकान या ध्यान की दिक्कत बताते हैं। थके हुए हों तो गाड़ी मत चलाइए। सड़क किनारे सुरक्षित जगह रुककर 15-20 मिनट आराम कीजिए, फिर आगे बढ़िए।",
      safetyAnxious: "आपके जवाब बेचैनी या घबराहट बताते हैं। गाड़ी चलाते समय घबराहट बढ़े तो तुरंत सुरक्षित जगह गाड़ी रोकिए और कुछ गहरी साँसें लीजिए।",
    },
    en: {
      eyebrow: "A quick check-in first",
      title: "Mind Check",
      intro: "Over the last 2 weeks, how much have these things bothered you? There are no right or wrong answers, pick what feels true.",
      anxiety: "Anxiety check (GAD-7, 7 questions)",
      depression: "Depression check (PHQ-9, 9 questions)",
      consent: "I understand this is not a medical diagnosis. The camera only reads facial expressions and nothing is recorded.",
      consentNeeded: "Please agree to continue.",
      question: "Question",
      voiceOn: "🔊 Voice on",
      voiceOff: "🔇 Voice off",
      back: "← Back",
      listening: "🎙️ Listening… please speak",
      heard: "You said: ",
      noMatch: "Could not understand. Tap an option above or speak again.",
      noVoice: "Voice answers are not supported in this browser. Tap an option.",
      confirmPrefix: "You said ",
      confirmQuestion: "Is that correct? Say yes or no.",
      cameraBlocked: "Camera not available. That is fine, your answers and score are unaffected.",
      cameraModel: "The expression model could not load. Your answers and your score are unaffected.",
      detecting: "AI DETECTING",
      tension: "Tension",
      detailsTitle: "Your details",
      detailsNote: "These details will be written on your report.",
      name: "Full name",
      mobile: "Mobile number",
      email: "Email (optional)",
      required: "Please enter your name and a valid mobile number.",
      invalidEmail: "That email does not look right.",
      seeResult: "See my result",
      reportTitle: "Your report",
      reportHeading: "Mental Wellness Screening Report",
      date: "Date",
      instrument: "Instrument",
      refNo: "Reference",
      totalScore: "Total score",
      scaleTitle: "Score ranges and what they mean",
      scoreHere: "Your score",
      colRange: "Score",
      colCategory: "Category",
      colMeaning: "What it usually means",
      severity: "Severity bands",
      yourScore: "< your score",
      tips: "Suggestions for you",
      expression: "Facial expression (session average)",
      immediate: "Immediate support",
      immediateNote: "You reported thoughts of hurting yourself. Please treat this as urgent and talk to someone now:",
      doctors: "Care team",
      book: "Book appointment",
      mitraCalls: "Your result is serious. MITRA will call a doctor for you.",
      report: "⬇ PDF report",
      certificate: "⬇ Certificate",
      mitra: "Talk to MITRA",
      dashboard: "Dashboard",
      retake: "Retake",
      note: "This is a screening, not a medical diagnosis.",
      lang: "हिन्दी",
      repeat: "🔁 Repeat question",
      keys: "Keyboard: 1-4 to answer, \u2190 to go back",
      liveTitle: "Live facial expression",
      faceWait: "Starting the camera…",
      faceOk: "Face detected",
      faceNone: "No face visible. Sit in front of the camera in good light.",
      recorded: "Answer saved",
      timeline: "Your expression on each question",
      insightTitle: "Face and answers together",
      insightMismatch: "Your answers are mild, but your face showed tension while you answered. There may be more going on than you are saying. Please talk to someone you trust or to our specialist once.",
      insightConfirm: "Both your answers and your facial expressions point towards stress. Please do not delay, talk to a specialist.",
      insightCalm: "Your face stayed calm, but your answers are serious. We give your answers the most weight, so please talk to a specialist.",
      insightOk: "Your answers and your facial expressions agree with each other.",
      tierTitle: "Priority",
      tierUrgent: "Urgent help needed",
      tierElevated: "Needs attention",
      tierNormal: "Normal",
      rushed: "You gave every answer very quickly and all the same. You may not have read them closely. For an accurate result, please retake it calmly.",
      trendTitle: "Compared to your last check",
      trendFirst: "This is your first check. Future checks will be compared with it.",
      trendBetter: "Last time it was {prev}, now {now}. That is better, keep looking after yourself.",
      trendWorse: "Last time it was {prev}, now {now}. It has got a little worse, please do not take it lightly.",
      trendSame: "Last time it was {prev}, now {now}. About the same.",
      safetyTitle: "Important advice for driving",
      safetyDrowsy: "Your answers point to sleep, tiredness or focus problems. Do not drive while tired. Stop at a safe place and rest for 15-20 minutes before going on.",
      safetyAnxious: "Your answers point to restlessness or anxiety. If anxiety rises while driving, stop at a safe place at once and take a few deep breaths.",
    },
  };

  const overlay = document.getElementById("mindcheck");
  const body = document.getElementById("mindcheckBody");
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.className = "mc-video";
  const state = {
    lang: "hi",
    voiceOn: true,
    step: "home",
    locked: false,
    kind: "anxiety",
    index: 0,
    answers: [],
    confirming: false,
    pending: null,
    consent: false,
    details: { name: "", mobile: "", email: "" },
    result: null,
    trace: [],
    times: [],
    qStart: 0,
  };
  const NEGATIVE = ["sad", "angry", "fearful", "disgusted"];
  const voice = { token: 0, recognition: null, retries: 0 };
  const camera = { wanted: false, stream: null, timer: null, sums: {}, frames: 0, tension: [], error: "", smooth: {}, misses: 0, top: "neutral" };
  let live = null;

  const t = () => ui[state.lang];

  function h(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    for (const child of children) if (child !== null && child !== undefined) node.append(child);
    return node;
  }

  function button(label, onClick, className = "mc-primary") {
    const node = h("button", className, label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function langToggle(afterChange) {
    return button(t().lang, () => {
      state.lang = state.lang === "hi" ? "en" : "hi";
      afterChange();
    }, "mc-chip");
  }

  // ---------- voice (speechSynthesis out, SpeechRecognition in) ----------

  const bcp47 = (lang) => (lang === "hi" ? "hi-IN" : "en-IN");
  const speechOutSupported = () => "speechSynthesis" in window;
  const recognitionCtor = () => window.SpeechRecognition || window.webkitSpeechRecognition;

  function pickVoice(lang) {
    const wanted = bcp47(lang);
    const voices = window.speechSynthesis.getVoices();
    return voices.find((v) => v.lang === wanted)
      || voices.find((v) => v.lang.replace("_", "-").startsWith(lang === "hi" ? "hi" : "en"))
      || null;
  }

  function cancelSpeech() {
    if (speechOutSupported()) window.speechSynthesis.cancel();
  }

  // Calls onEnd after speaking, also on error or when TTS is missing, so the caller can always chain the mic.
  function speak(text, lang, onEnd) {
    if (!speechOutSupported()) { onEnd?.(); return; }
    const synth = window.speechSynthesis;
    synth.cancel();
    const say = () => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = bcp47(lang);
      utterance.rate = 0.95;
      const chosen = pickVoice(lang);
      if (chosen) utterance.voice = chosen;
      let done = false;
      const finish = () => { if (done) return; done = true; onEnd?.(); };
      utterance.onend = finish;
      utterance.onerror = finish;
      synth.speak(utterance);
    };
    if (synth.getVoices().length === 0) {
      let fired = false;
      const run = () => { if (fired) return; fired = true; say(); };
      synth.addEventListener("voiceschanged", run, { once: true });
      window.setTimeout(run, 700);
      return;
    }
    say();
  }

  function stopListening() {
    const current = voice.recognition;
    voice.recognition = null;
    if (current) { try { current.abort(); } catch { /* already stopped */ } }
  }

  function setNote(text, heard) {
    if (!live) return;
    live.transcript.textContent = heard ? `${t().heard}“${heard}”` : "";
    live.note.textContent = text || "";
  }

  function startListening(token) {
    if (token !== voice.token || !state.voiceOn) return;
    const Ctor = recognitionCtor();
    if (!Ctor) { setNote(t().noVoice); return; }
    stopListening();
    const recognition = new Ctor();
    recognition.lang = bcp47(state.lang);
    recognition.interimResults = false;
    recognition.maxAlternatives = 4;
    recognition.continuous = false;
    let got = false;
    recognition.onresult = (event) => {
      got = true;
      const result = event.results[0];
      const alternatives = [];
      for (let i = 0; i < result.length; i += 1) alternatives.push(result[i].transcript);
      if (token === voice.token) handleTranscript(alternatives, token);
    };
    recognition.onerror = () => {};
    recognition.onend = () => {
      if (voice.recognition !== recognition) return;
      voice.recognition = null;
      if (got || token !== voice.token) return;
      voice.retries += 1;
      if (voice.retries < MAX_VOICE_RETRIES) window.setTimeout(() => startListening(token), 300);
      else setNote(t().noMatch);
    };
    voice.recognition = recognition;
    setNote(t().listening);
    try { recognition.start(); } catch { /* start called twice */ }
  }

  function askQuestionAloud() {
    voice.token += 1;
    const token = voice.token;
    voice.retries = 0;
    stopListening();
    cancelSpeech();
    if (!state.voiceOn) return;
    const prompt = state.confirming && state.pending !== null
      ? `${t().confirmPrefix}"${labels[state.lang][state.pending]}". ${t().confirmQuestion}`
      : `${questions[state.kind][state.index][state.lang]}. ${labels[state.lang].join(", ")}.`;
    speak(prompt, state.lang, () => startListening(token));
  }

  function handleTranscript(alternatives, token) {
    const heard = alternatives[0] || "";
    setNote("", heard);
    for (const alt of alternatives) {
      if (state.confirming) {
        const yesNo = MC.parseYesNo(alt, state.lang);
        if (yesNo === true) { select(state.pending); return; }
        if (yesNo === false) { state.confirming = false; state.pending = null; askQuestionAloud(); return; }
        continue;
      }
      const value = MC.parseVoiceAnswer(alt, state.lang);
      if (value === null) continue;
      if (confirmIndices.includes(state.index)) {
        state.pending = value;
        state.confirming = true;
        askQuestionAloud();
      } else {
        select(value);
      }
      return;
    }
    voice.retries += 1;
    if (voice.retries < MAX_VOICE_RETRIES) startListening(token);
    else setNote(t().noMatch, heard);
  }

  // ---------- camera + face expressions (face-api.js from CDN) ----------

  let faceApiReady = null;
  function loadFaceApi() {
    if (faceApiReady) return faceApiReady;
    faceApiReady = new Promise((resolve) => {
      const fail = () => { faceApiReady = null; resolve(null); };
      const script = document.createElement("script");
      script.src = FACE_API_SRC;
      script.onerror = fail;
      script.onload = async () => {
        const api = window.faceapi;
        if (!api) { fail(); return; }
        try {
          await Promise.all([api.nets.tinyFaceDetector.loadFromUri(FACE_WEIGHTS), api.nets.faceExpressionNet.loadFromUri(FACE_WEIGHTS)]);
          resolve(api);
        } catch { fail(); }
      };
      document.head.appendChild(script);
    });
    return faceApiReady;
  }

  function resetCameraStats() {
    camera.sums = {};
    camera.frames = 0;
    camera.tension = [];
    camera.error = "";
    camera.smooth = {};
    camera.misses = 0;
    camera.top = "neutral";
  }
  async function startCamera() {
    if (camera.wanted) return;
    camera.wanted = true;
    setFaceStatus("wait");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      if (!camera.wanted) { stream.getTracks().forEach((track) => track.stop()); return; }
      camera.stream = stream;
      video.srcObject = stream;
      await video.play().catch(() => {});
      const api = await loadFaceApi();
      if (!api) { camera.error = "cameraModel"; refreshCameraNote(); return; }
      scanFace();
    } catch {
      camera.error = "cameraBlocked";
      camera.wanted = false;
      refreshCameraNote();
    }
  }
  // ~3 scans a second. Raw expressions are smoothed (EMA) so the live bars move calmly instead of flickering.
  function scanFace() {
    if (!camera.wanted || !window.faceapi) return;
    const options = new window.faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.4 });
    window.faceapi.detectSingleFace(video, options).withFaceExpressions().then((detected) => {
      if (!camera.wanted) return;
      if (detected) {
        camera.misses = 0;
        const raw = detected.expressions;
        for (const key of MC.expressionOrder) {
          const previous = camera.smooth[key] ?? raw[key] ?? 0;
          camera.smooth[key] = previous * 0.6 + (raw[key] || 0) * 0.4;
          camera.sums[key] = (camera.sums[key] || 0) + (raw[key] || 0);
        }
        camera.frames += 1;
        // Anything that is not calm (neutral + happy) counts towards the tension signal, clamped to 6-94%.
        camera.tension.push(Math.max(6, Math.min(94, Math.round((1 - ((raw.neutral || 0) + (raw.happy || 0))) * 100))));
        camera.top = MC.expressionOrder.slice().sort((a, b) => camera.smooth[b] - camera.smooth[a])[0];
        updateLive(detected.detection && detected.detection.box);
      } else {
        camera.misses += 1;
        if (camera.misses >= 3) setFaceStatus("none");
      }
      camera.timer = window.setTimeout(scanFace, 350);
    }).catch(() => { if (camera.wanted) camera.timer = window.setTimeout(scanFace, 1200); });
  }
  function stopCamera() {
    camera.wanted = false;
    if (camera.timer) window.clearTimeout(camera.timer);
    camera.timer = null;
    if (camera.stream) camera.stream.getTracks().forEach((track) => track.stop());
    camera.stream = null;
    video.srcObject = null;
  }
  function setFaceStatus(kind) {
    if (!live) return;
    live.status.dataset.state = kind;
    live.status.textContent = kind === "ok" ? t().faceOk : kind === "none" ? t().faceNone : t().faceWait;
    if (kind !== "ok") live.box.hidden = true;
  }
  function updateLive(box) {
    if (!live) return;
    setFaceStatus("ok");
    const meta = MC.expressionMeta[camera.top];
    live.emoji.textContent = meta.emoji;
    live.emoName.textContent = meta[state.lang];
    for (const key of MC.expressionOrder) {
      const pct = Math.round((camera.smooth[key] || 0) * 100);
      live.bars[key].fill.style.width = `${pct}%`;
      live.bars[key].pct.textContent = `${pct}%`;
      live.bars[key].row.classList.toggle("top", key === camera.top);
    }
    if (box && video.videoWidth && video.videoHeight) {
      // The preview is mirrored, so the box is mirrored too.
      live.box.hidden = false;
      live.box.style.left = `${100 - ((box.x + box.width) / video.videoWidth) * 100}%`;
      live.box.style.top = `${(box.y / video.videoHeight) * 100}%`;
      live.box.style.width = `${(box.width / video.videoWidth) * 100}%`;
      live.box.style.height = `${(box.height / video.videoHeight) * 100}%`;
    }
  }
  function refreshCameraNote() {
    if (live && camera.error) live.cameraNote.textContent = t()[camera.error];
  }

  // ---------- steps ----------
  function stopEverything() {
    body.classList.remove("mc-sheet");
    voice.token += 1;
    stopListening();
    cancelSpeech();
    stopCamera();
  }
  function renderHome() {
    state.step = "home";
    body.classList.remove("mc-wide");
    stopEverything();
    live = null;
    const consent = h("input");
    consent.type = "checkbox";
    consent.checked = state.consent;
    consent.addEventListener("change", () => { state.consent = consent.checked; error.textContent = ""; });
    const error = h("p", "mc-error");
    const begin = (kind) => {
      if (!state.consent) { error.textContent = t().consentNeeded; return; }
      startScreening(kind);
    };
    body.replaceChildren(
      h("div", "mc-row", h("p", "mc-eyebrow", t().eyebrow), langToggle(renderHome)),
      h("h2", "mc-title", t().title),
      h("p", "mc-copy", t().intro),
      h("label", "mc-consent", consent, h("span", "", t().consent)),
      error,
      button(t().anxiety, () => begin("anxiety")),
      h("div", "mc-gap"),
      button(t().depression, () => begin("depression")),
    );
  }
  function startScreening(kind) {
    state.kind = kind;
    state.index = 0;
    state.answers = Array(questions[kind].length).fill(null);
    state.trace = Array(questions[kind].length).fill(null);
    state.times = Array(questions[kind].length).fill(0);
    state.confirming = false;
    state.pending = null;
    resetCameraStats();
    state.step = "questions";
    renderQuestionScreen();
    startCamera();
  }
  // The screen is built once and the question is swapped inside it, so the camera preview never re-mounts (a re-mounted
  // <video> pauses and the face reading would freeze on the first question).
  function renderQuestionScreen() {
    const list = questions[state.kind];
    const eyebrow = h("p", "mc-eyebrow");
    const dots = h("div", "mc-dots");
    const dotNodes = list.map(() => { const dot = h("span", "mc-dot"); dots.append(dot); return dot; });
    const voiceToggle = button(state.voiceOn ? t().voiceOn : t().voiceOff, () => {
      state.voiceOn = !state.voiceOn;
      if (!state.voiceOn) { voice.token += 1; stopListening(); cancelSpeech(); setNote(""); }
      voiceToggle.textContent = state.voiceOn ? t().voiceOn : t().voiceOff;
      if (state.voiceOn) askQuestionAloud();
    }, "mc-chip");
    const lang = langToggle(() => { state.confirming = false; state.pending = null; renderQuestionScreen(); });
    const boxEl = h("div", "mc-facebox");
    boxEl.hidden = true;
    const status = h("div", "mc-status");
    const cameraNote = h("p", "mc-note");
    const camWrap = h("div", "mc-camera", video, boxEl, status);
    const emoji = h("div", "mc-emoji", "\u{1F642}");
    const emoName = h("strong", "mc-emoname", MC.expressionMeta.neutral[state.lang]);
    const bars = {};
    const barList = h("div", "mc-emobars");
    for (const key of MC.expressionOrder) {
      const meta = MC.expressionMeta[key];
      const fill = h("div", "mc-fill");
      const pct = h("span", "", "0%");
      const row = h("div", "mc-emorow", h("span", "mc-emolabel", `${meta.emoji} ${meta[state.lang]}`), h("div", "mc-dist-bar", fill), pct);
      bars[key] = { fill, pct, row };
      barList.append(row);
    }
    const emoPanel = h("div", "mc-emopanel", h("p", "mc-emotitle", t().liveTitle), h("div", "mc-emohead", emoji, emoName), barList);
    const qnum = h("p", "mc-qnum");
    const qtext = h("h2", "mc-question");
    const options = h("div", "mc-options");
    const transcript = h("p", "mc-transcript");
    const note = h("p", "mc-note");
    const qcard = h("div", "mc-qcard", qnum, qtext, options, transcript, note);

    const back = button(t().back, goBack, "mc-back");
    const repeat = button(t().repeat, () => { state.confirming = false; state.pending = null; askQuestionAloud(); }, "mc-back");

    live = {
      eyebrow, dots: dotNodes, status, box: boxEl, cameraNote, emoji, emoName, bars,
      qnum, qtext, options, transcript, note, qcard, back,
    };
    body.replaceChildren(
      h("div", "mc-row", eyebrow, h("div", "mc-chips", voiceToggle, lang)),
      dots,
      h("div", "mc-stage",
        h("div", "mc-side", camWrap, cameraNote, emoPanel),
        h("div", "mc-main", qcard, h("div", "mc-row mc-below", back, repeat), h("p", "mc-fine", t().keys)),
      ),
    );
    body.classList.add("mc-wide");
    video.play().catch(() => {});
    setFaceStatus(camera.wanted && camera.frames ? "ok" : "wait");
    refreshCameraNote();
    showQuestion();
  }

  function showQuestion() {
    const list = questions[state.kind];
    state.qStart = Date.now();
    live.eyebrow.textContent = `${state.kind === "anxiety" ? "GAD-7" : "PHQ-9"} \u00b7 ${t().question} ${state.index + 1}/${list.length}`;
    live.dots.forEach((dot, i) => {
      dot.className = `mc-dot${i < state.index ? " done" : ""}${i === state.index ? " now" : ""}`;
    });
    live.qnum.textContent = `${t().question} ${state.index + 1}`;
    live.qtext.textContent = list[state.index][state.lang];
    live.options.replaceChildren();
    labels[state.lang].forEach((label, value) => {
      const opt = button("", () => select(value), "mc-option");
      opt.dataset.value = String(value);
      opt.append(h("span", "mc-key", String(value + 1)), h("span", "mc-optlabel", label));
      live.options.append(opt);
    });
    live.transcript.textContent = "";
    live.note.textContent = "";
    live.back.disabled = state.index === 0;
    // Restart the slide-in animation so the change of question is obvious.
    live.qcard.classList.remove("mc-enter");
    void live.qcard.offsetWidth;
    live.qcard.classList.add("mc-enter");
    askQuestionAloud();
  }

  function goBack() {
    if (state.index === 0 || state.locked) return;
    state.index -= 1;
    state.confirming = false;
    state.pending = null;
    showQuestion();
  }

  // Highlights the chosen option and shows "saved" before moving on, so the answer never feels lost.
  function select(value) {
    if (state.locked) return;
    state.locked = true;
    voice.token += 1;
    stopListening();
    cancelSpeech();
    const chosen = live.options.querySelector(`[data-value="${value}"]`);
    live.options.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    if (chosen) chosen.classList.add("selected");
    live.note.textContent = t().recorded;
    window.setTimeout(() => { state.locked = false; record(value); }, 450);
  }

  function record(value) {
    state.answers[state.index] = value;
    state.times[state.index] = (Date.now() - state.qStart) / 1000;
    // The expression the camera read at the moment of this answer, kept for the per-question timeline.
    state.trace[state.index] = camera.frames ? { key: camera.top, neg: NEGATIVE.reduce((sum, key) => sum + (camera.smooth[key] || 0), 0) } : null;
    state.confirming = false;
    state.pending = null;
    if (state.index < questions[state.kind].length - 1) {
      state.index += 1;
      showQuestion();
    } else {
      stopCamera();
      renderDetails();
    }
  }

  document.addEventListener("keydown", (event) => {
    if (state.step !== "questions" || !live || overlay.hidden) return;
    if (event.key >= "1" && event.key <= "4") select(Number(event.key) - 1);
    else if (event.key === "ArrowLeft") goBack();
  });

  function renderDetails(errorText = "") {
    state.step = "details";
    body.classList.remove("mc-wide");
    stopEverything();
    live = null;
    const field = (label, key, type, mode) => {
      const input = h("input");
      input.type = type;
      if (mode) input.inputMode = mode;
      input.value = state.details[key];
      input.addEventListener("input", () => { state.details[key] = input.value; });
      return h("label", "mc-field", h("span", "", label), input);
    };
    body.replaceChildren(
      h("div", "mc-row", h("p", "mc-eyebrow", t().detailsTitle), langToggle(() => renderDetails(errorText))),
      h("h2", "mc-title", t().detailsTitle),
      h("p", "mc-copy", t().detailsNote),
      field(t().name, "name", "text"),
      field(t().mobile, "mobile", "tel", "numeric"),
      field(t().email, "email", "email"),
      h("p", "mc-error", errorText),
      button(t().seeResult, submit),
    );
  }

  function submit() {
    const { name, mobile, email } = state.details;
    const digits = mobile.replace(/\D/g, "");
    if (!name.trim() || digits.length < 10 || digits.length > 13) { renderDetails(t().required); return; }
    if (email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim())) { renderDetails(t().invalidEmail); return; }

    const values = questions[state.kind].map((_, i) => state.answers[i] ?? 0);
    const score = values.reduce((sum, value) => sum + value, 0);
    const band = MC.bandFor(state.kind, score);
    const bucket = MC.bucketFor(band);
    const selfHarm = questions[state.kind].some((question, i) => question.selfHarm === true && values[i] > 0);
    const distribution = MC.expressionDistribution(camera.sums, camera.frames);
    const cameraPct = camera.tension.length ? Math.round(camera.tension.reduce((a, b) => a + b, 0) / camera.tension.length) : 0;
    const dominantKey = distribution[0] ? distribution[0].key : "";
    const createdAt = new Date().toISOString();

    // Own logic on top of the standard score: does the face agree with the answers? Only trusted with enough frames.
    const negPct = distribution.filter((row) => NEGATIVE.includes(row.key)).reduce((sum, row) => sum + row.pct, 0);
    const enough = camera.frames >= 5;
    const faceConcern = enough && negPct >= 45;
    let insight = "";
    if (enough) {
      if (faceConcern) insight = bucket === "low" || bucket === "mild" ? "insightMismatch" : "insightConfirm";
      else insight = bucket === "high" ? "insightCalm" : "insightOk";
    }

    // More own logic: hesitation on the self-harm question, rushed straight-lining, and one priority tier for MITRA.
    const selfIndex = questions[state.kind].findIndex((question) => question.selfHarm === true);
    const hesitatedSelfHarm = selfIndex >= 0 && values[selfIndex] === 0 && state.times[selfIndex] > 15;
    const avgTime = state.times.reduce((a, b) => a + b, 0) / state.times.length;
    const rushed = values.every((value) => value === values[0]) && avgTime < 4;
    const tier = bucket === "high" || selfHarm ? "urgent" : bucket === "moderate" || faceConcern || hesitatedSelfHarm ? "elevated" : "normal";

    // Driver safety: sleep / tiredness / focus (PHQ-9) or nervousness / restlessness (GAD-7) answered "more than half the days" or worse.
    const safetyIndexes = state.kind === "depression" ? [2, 3, 6] : [0, 4];
    const safety = safetyIndexes.some((i) => values[i] >= 2) ? (state.kind === "depression" ? "safetyDrowsy" : "safetyAnxious") : "";

    // Trend against the last saved check of the same kind (lower is better for both scales).
    let prevScore = null;
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      const last = Array.isArray(stored) ? stored.find((row) => row && row.kind === state.kind && typeof row.score === "number") : null;
      if (last) prevScore = last.score;
    } catch { /* no history available */ }

    state.result = {
      kind: state.kind, score, band, bucket, selfHarm, distribution, dominantKey, cameraPct, createdAt, faceConcern, insight,
      trace: state.trace.slice(), tier, hesitatedSelfHarm, rushed, safety, prevScore,
    };
    saveSubmission({
      score, band, selfHarm, kind: state.kind, name, email, mobile,
      expression: dominantKey ? MC.expressionMeta[dominantKey].en : "", cameraPct, distribution, createdAt, faceConcern,
      tier, prevScore, insightText: insight ? ui.en[insight] : "", safetyText: safety ? ui.en[safety] : "",
    });
    renderResult();
  }

  function saveSubmission(row) {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      const rows = Array.isArray(stored) ? stored : [];
      localStorage.setItem(STORAGE_KEY, JSON.stringify([row, ...rows]));
    } catch { /* private mode or quota: the on-screen result is unaffected */ }
  }

  function reportData() {
    const r = state.result;
    return {
      kind: r.kind, name: state.details.name, email: state.details.email, mobile: state.details.mobile,
      score: r.score, band: r.band, distribution: r.distribution,
      dominant: r.dominantKey ? MC.expressionMeta[r.dominantKey].en : "", selfHarm: r.selfHarm, createdAt: r.createdAt,
      tier: r.tier, prevScore: r.prevScore, insightText: r.insight ? ui.en[r.insight] : "", safetyText: r.safety ? ui.en[r.safety] : "",
    };
  }

  const BAND_MEANING = {
    hi: {
      Minimal: "बहुत कम या कोई लक्षण नहीं",
      Mild: "हल्के लक्षण; खुद का ध्यान रखें",
      Moderate: "रोज़मर्रा पर असर; काउंसलिंग बेहतर",
      "Moderately severe": "काफी लक्षण; विशेषज्ञ की मदद ज़रूरी",
      Severe: "गंभीर लक्षण; तुरंत विशेषज्ञ की मदद",
    },
    en: {
      Minimal: "Little or no symptoms",
      Mild: "Mild symptoms; self-care and monitoring",
      Moderate: "Symptoms affecting daily life; counselling advised",
      "Moderately severe": "Significant symptoms; professional support advised",
      Severe: "Severe symptoms; prompt professional help advised",
    },
  };
  const colour = (band) => `rgb(${Report.BAND_COLORS[band].join(",")})`;
  const bandName = (band, lang) => (lang === "hi" ? MC.bandHi[band] : band);

  // One coloured segment per band, sized by how many scores fall in it, with a marker at the reader's score.
  function gaugeEl(kind, score, lang) {
    const total = maxScore[kind] + 1;
    const marker = h("div", "mc-gauge-marker", h("span", "", `${t().scoreHere}: ${score}`));
    marker.style.left = `${((score + 0.5) / total) * 100}%`;
    const bar = h("div", "mc-gauge-bar");
    const labelRow = h("div", "mc-gauge-labels");
    let start = 0;
    for (const row of MC.bandScale[kind]) {
      const count = row.upTo - start + 1;
      const seg = h("div", "mc-gauge-seg");
      seg.style.flex = String(count);
      seg.style.background = colour(row.band);
      bar.append(seg);
      const label = h("div", "mc-gauge-label", h("strong", "", `${start}-${row.upTo}`), h("span", "", bandName(row.band, lang)));
      label.style.flex = String(count);
      labelRow.append(label);
      start = row.upTo + 1;
    }
    return h("div", "mc-gauge", marker, bar, labelRow);
  }

  function rangeTable(r, lang) {
    const table = h("div", "mc-rtable");
    table.append(h("div", "mc-rrow head", h("span", "", t().colRange), h("span", "", t().colCategory), h("span", "", t().colMeaning)));
    for (const row of MC.bandRowsFor(r.kind)) {
      const mine = row.band === r.band;
      const dot = h("i", "mc-dot2");
      dot.style.background = colour(row.band);
      table.append(h("div", `mc-rrow${mine ? " mine" : ""}`, h("span", "", row.range), h("span", "", dot, bandName(row.band, lang)), h("span", "", BAND_MEANING[lang][row.band], mine ? h("em", "", ` ${t().yourScore}`) : null)));
    }
    return table;
  }

  function detailsGrid(r) {
    const item = (label, value) => h("div", "mc-detail", h("small", "", label), h("strong", "", value));
    return h("div", "mc-details",
      item(t().name, state.details.name || "-"),
      item(t().mobile, state.details.mobile || "-"),
      item(t().email.replace(/\s*\(.*\)/, ""), state.details.email || "-"),
      item(t().instrument, Report.typeLabel(r.kind)),
      item(t().date, Report.istStamp(r.createdAt)),
      item(t().refNo, Report.referenceNo(r.createdAt)),
    );
  }

  function savePdf(make, filename) {
    return Promise.resolve(make()).then((pdf) => pdf.save(filename));
  }

  function renderResult() {
    state.step = "result";
    body.classList.remove("mc-wide");
    stopEverything();
    body.classList.add("mc-sheet");
    live = null;
    Report.loadLetterhead();
    const r = state.result;
    const lang = state.lang;

    const headerImg = h("img", "mc-lh");
    headerImg.src = "/assets/letterhead-header.jpeg";
    headerImg.alt = "Positive Mind Care and Research Centre";
    const footerImg = h("img", "mc-lh");
    footerImg.src = "/assets/letterhead-footer.jpeg";
    footerImg.alt = "Positive Mind Care contact details";

    const tips = h("ul", "mc-list");
    MC.solutions[lang][r.bucket].forEach((tip) => tips.append(h("li", "", tip)));

    const tierLabel = { urgent: t().tierUrgent, elevated: t().tierElevated, normal: t().tierNormal }[r.tier];
    const pill = h("span", "mc-pill", bandName(r.band, lang));
    pill.style.background = colour(r.band);
    const panel = h("section", "mc-panel",
      h("div", "mc-panel-top",
        h("div", "", h("small", "", t().totalScore), h("p", "mc-score", String(r.score), h("span", "", ` / ${maxScore[r.kind]}`))),
        h("div", "mc-panel-right", pill, h("p", `mc-tier ${r.tier}`, `${t().tierTitle}: ${tierLabel}`)),
      ),
      gaugeEl(r.kind, r.score, lang),
    );
    panel.style.borderLeftColor = colour(r.band);

    const nodes = [
      h("div", "mc-row mc-sheet-title",
        h("div", "", h("h2", "mc-title", t().reportHeading), h("p", "mc-fine", `${Report.typeLabel(r.kind)}  |  ${lang === "hi" ? "गोपनीय" : "Confidential"}`)),
        langToggle(renderResult),
      ),
      detailsGrid(r),
      panel,
    ];

    if (r.tier === "urgent") nodes.push(h("p", "mc-alert", t().mitraCalls));
    nodes.push(h("h3", "mc-sub", t().scaleTitle), rangeTable(r, lang));
    nodes.push(h("h3", "mc-sub", lang === "hi" ? "व्याख्या" : "Interpretation"), h("p", "mc-copy", MC.bandExplanations[lang][r.kind][r.band]));

    if (r.rushed) nodes.push(h("p", "mc-insight insightMismatch", t().rushed));
    const trendText = r.prevScore === null ? t().trendFirst
      : (r.score < r.prevScore ? t().trendBetter : r.score > r.prevScore ? t().trendWorse : t().trendSame)
        .replace("{prev}", r.prevScore).replace("{now}", r.score);
    nodes.push(h("h3", "mc-sub", t().trendTitle), h("p", "mc-copy", trendText));
    if (r.safety) nodes.push(h("h3", "mc-sub", t().safetyTitle), h("p", "mc-alert mc-safety", t()[r.safety]));

    nodes.push(h("h3", "mc-sub", t().tips), tips);

    if (r.distribution.length) {
      const dist = h("div", "mc-dist");
      for (const row of r.distribution) {
        const meta = MC.expressionMeta[row.key];
        const bar = h("div", "mc-dist-bar", h("div", "mc-fill"));
        bar.firstChild.style.width = `${row.pct}%`;
        dist.append(h("div", "mc-dist-row", h("span", "", `${meta.emoji} ${meta[lang]}`), bar, h("span", "", `${row.pct}%`)));
      }
      nodes.push(h("h3", "mc-sub", t().expression), dist);
    }

    if (r.insight) nodes.push(h("h3", "mc-sub", t().insightTitle), h("p", `mc-insight ${r.insight}`, t()[r.insight]));
    if (r.trace.some(Boolean)) {
      const line = h("div", "mc-timeline");
      r.trace.forEach((entry, i) => {
        if (!entry) return;
        line.append(h("span", `mc-tick${entry.neg >= 0.45 ? " neg" : ""}`, h("small", "", `Q${i + 1}`), MC.expressionMeta[entry.key].emoji));
      });
      nodes.push(h("h3", "mc-sub", t().timeline), line);
    }

    if (r.selfHarm) {
      const help = h("ul", "mc-list");
      MC.crisisHelplines[lang].forEach((line) => help.append(h("li", "", line)));
      nodes.push(h("h3", "mc-sub", t().immediate), h("p", "mc-copy", t().immediateNote), help);
    }

    const dashLink = h("a", "mc-linkbtn", t().dashboard);
    dashLink.href = "/dashboard";
    dashLink.target = "_blank";
    nodes.push(
      h("div", "mc-actions",
        button(t().report, () => savePdf(() => Report.buildReport(reportData()), "mental-wellness-screening-report.pdf"), "mc-secondary"),
        button(t().certificate, () => savePdf(() => Report.buildCertificate(reportData()), "mental-health-awareness-certificate.pdf"), "mc-secondary"),
        dashLink,
        button(t().retake, renderHome, "mc-secondary"),
      ),
      h("p", "mc-fine", t().note),
      button(t().mitra, finish),
    );
    body.replaceChildren(headerImg, h("div", "mc-sheet-body", ...nodes), footerImg);
    body.scrollTop = 0;
  }

  async function finish() {
    const r = state.result;
    stopEverything();
    overlay.hidden = true;
    document.body.classList.remove("mindcheck-open");
    // The answers the driver marked most often, in Hindi, so MITRA can talk about them.
    const ranked = questions[r.kind].map((q, i) => ({ text: q.hi, value: state.answers[i] ?? 0 })).filter((x) => x.value >= 2).sort((a, b) => b.value - a.value);
    const symptoms = ranked.slice(0, 3).map((x) => x.text);
    await window.mitraDeliverMindcheck({ kind: r.kind, score: r.score, band: r.band, bucket: r.bucket, selfHarm: r.selfHarm, faceConcern: r.faceConcern, tier: r.tier, symptoms });
  }

  document.body.classList.add("mindcheck-open");
  overlay.hidden = false;
  renderHome();
})();
