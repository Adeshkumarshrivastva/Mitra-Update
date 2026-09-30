/* Static screening data + logic, ported as-is from Minds-Ai (src/lib/screening.ts and voice matching). */
window.MC = (() => {
const questions = {
  anxiety: [
    { en: "Feeling nervous, anxious, or on edge", hi: "घबराहट, बेचैनी या तनाव महसूस करना" },
    { en: "Not being able to stop or control worrying", hi: "चिंता को रोकना या नियंत्रित करना मुश्किल लगना" },
    { en: "Worrying too much about different things", hi: "अलग-अलग बातों को लेकर ज़्यादा चिंता करना" },
    { en: "Trouble relaxing", hi: "आराम करने में दिक्कत होना" },
    { en: "Being so restless that it is hard to sit still", hi: "इतनी बेचैनी होना कि बैठना मुश्किल हो" },
    { en: "Becoming easily annoyed or irritable", hi: "आसानी से चिड़चिड़ा या गुस्सा हो जाना" },
    { en: "Feeling afraid as if something awful might happen", hi: "ऐसा महसूस होना जैसे कुछ बुरा होने वाला है" },
  ],
  depression: [
    { en: "Little interest or pleasure in doing things", hi: "किसी काम में मन न लगना या मज़ा न आना" },
    { en: "Feeling down, depressed, or hopeless", hi: "उदास, निराश या हताश महसूस करना" },
    { en: "Trouble falling asleep, staying asleep, or sleeping too much", hi: "नींद न आना, नींद टूटना या ज़्यादा सोना" },
    { en: "Feeling tired or having little energy", hi: "थकान महसूस करना या ऊर्जा की कमी" },
    { en: "Poor appetite or overeating", hi: "भूख न लगना या ज़्यादा खाना" },
    { en: "Feeling bad about yourself or like a failure", hi: "खुद को लेकर बुरा महसूस करना" },
    { en: "Trouble concentrating on things", hi: "ध्यान लगाने में दिक्कत होना" },
    { en: "Moving slowly or being very fidgety", hi: "इतना धीरे या बेचैन होना कि दूसरे नोटिस करें" },
    { en: "Thoughts of being better off dead or hurting yourself", hi: "जीने से बेहतर न होना या खुद को नुकसान पहुंचाने के विचार", selfHarm: true },
  ],
};

const labels = {
  en: ["Not at all", "Several days", "More than half the days", "Nearly every day"],
  hi: ["बिल्कुल नहीं", "कुछ दिन", "आधे से ज़्यादा दिन", "लगभग हर दिन"],
};

const bandScale = {
  anxiety: [
    { upTo: 4, band: "Minimal" },
    { upTo: 9, band: "Mild" },
    { upTo: 14, band: "Moderate" },
    { upTo: 21, band: "Severe" },
  ],
  depression: [
    { upTo: 4, band: "Minimal" },
    { upTo: 9, band: "Mild" },
    { upTo: 14, band: "Moderate" },
    { upTo: 19, band: "Moderately severe" },
    { upTo: 27, band: "Severe" },
  ],
};

const bandHi = {
  Minimal: "बहुत कम", Mild: "हल्का", Moderate: "मध्यम", "Moderately severe": "मध्यम-गंभीर", Severe: "गंभीर",
};

const bandEmoji = {
  Minimal: "🙂", Mild: "😐", Moderate: "😟", "Moderately severe": "😥", Severe: "😢",
};

const solutions = {
  en: {
    low: ["Take a 20-30 minute walk or light exercise daily.", "Keep a consistent sleep schedule (7-8 hours).", "Stay connected with friends and family."],
    mild: ["Practice 5-10 minutes of deep breathing daily.", "Reduce caffeine and screen time, especially before bed.", "Share your feelings with someone you trust."],
    moderate: ["Consider talking to a counsellor or therapist.", "Maintain a simple daily routine.", "Try relaxation techniques like meditation."],
    high: ["Please see a mental health professional or doctor as soon as possible.", "Tell someone you trust about how you are feeling.", "Reach out for support instead of being alone — asking for help is not a weakness."],
  },
  hi: {
    low: ["रोज़ाना 20-30 मिनट टहलना या हल्का व्यायाम करें।", "नींद का एक नियमित समय तय करें (7-8 घंटे)।", "अपने दोस्तों/परिवार से जुड़े रहें।"],
    mild: ["हर दिन 5-10 मिनट गहरी सांस लेने का अभ्यास करें।", "कैफीन और स्क्रीन टाइम कम करें, खासकर सोने से पहले।", "किसी भरोसेमंद व्यक्ति से अपनी भावनाएं साझा करें।"],
    moderate: ["किसी काउंसलर या थेरेपिस्ट से बात करने पर विचार करें।", "रोज़ की एक साधारण दिनचर्या बनाए रखें।", "रिलैक्सेशन तकनीक जैसे meditation आज़माएं।"],
    high: ["जल्द से जल्द किसी मानसिक स्वास्थ्य विशेषज्ञ या डॉक्टर से मिलें।", "किसी भरोसेमंद व्यक्ति को अपनी स्थिति के बारे में बताएं।", "अकेले रहने के बजाय सहयोग लें — मदद मांगना कमज़ोरी नहीं है।"],
  },
};

const bandExplanations = {
  en: {
    anxiety: {
      Minimal: "Your score suggests your current anxiety level is very low. That is a good sign — keep looking after your routine and sleep.",
      Mild: "Your score suggests a mild level of anxiety. You may feel anxious sometimes, but it likely does not affect your daily functioning much.",
      Moderate: "Your score suggests a moderate level of anxiety. This can start affecting daily life. Talking to a counsellor or therapist could help.",
      Severe: "Your score suggests a severe level of anxiety. Please do not ignore this — see a qualified mental health professional or doctor soon.",
    },
    depression: {
      Minimal: "Your score suggests your current depression level is very low. Keep maintaining your routine and social connections.",
      Mild: "Your score suggests a mild level of depression. You may feel low sometimes, but it likely is not affecting your functioning much right now.",
      Moderate: "Your score suggests a moderate level of depression. This can affect daily life. Talking to a counsellor or therapist would be helpful.",
      "Moderately severe": "Your score suggests a moderately severe level of depression. Please see a mental health professional soon.",
      Severe: "Your score suggests a severe level of depression. Please do not ignore this — see a qualified mental health professional or doctor as soon as possible.",
    },
  },
  hi: {
    anxiety: {
      Minimal: "आपका स्कोर बताता है कि इस समय आपकी चिंता का स्तर बहुत कम है। यह एक अच्छा संकेत है — फिर भी अपनी दिनचर्या और नींद का ध्यान रखते रहें।",
      Mild: "आपका स्कोर हल्के स्तर की चिंता दिखाता है। इसका मतलब है कि कभी-कभी चिंता महसूस होती है, लेकिन यह ज़्यादातर दिनों में आपके कामकाज को बहुत प्रभावित नहीं करती।",
      Moderate: "आपका स्कोर मध्यम स्तर की चिंता दिखाता है। यह आपके रोज़मर्रा के जीवन को प्रभावित कर सकती है। किसी काउंसलर या थेरेपिस्ट से बात करना फायदेमंद हो सकता है।",
      Severe: "आपका स्कोर गंभीर स्तर की चिंता दिखाता है। कृपया इसे नज़रअंदाज़ न करें — किसी योग्य मानसिक स्वास्थ्य विशेषज्ञ या डॉक्टर से जल्द से जल्द मिलें।",
    },
    depression: {
      Minimal: "आपका स्कोर बताता है कि इस समय डिप्रेशन का स्तर बहुत कम है। यह एक अच्छा संकेत है — अपनी दिनचर्या और सामाजिक जुड़ाव बनाए रखें।",
      Mild: "आपका स्कोर हल्के स्तर के डिप्रेशन का संकेत देता है। कभी-कभी उदासी महसूस हो सकती है, लेकिन यह अभी आपके कामकाज को बहुत प्रभावित नहीं कर रही।",
      Moderate: "आपका स्कोर मध्यम स्तर का डिप्रेशन दिखाता है। यह रोज़मर्रा के जीवन को प्रभावित कर सकता है। किसी काउंसलर या थेरेपिस्ट से बात करना फायदेमंद रहेगा।",
      "Moderately severe": "आपका स्कोर मध्यम-गंभीर स्तर का डिप्रेशन दिखाता है। कृपया जल्द ही किसी मानसिक स्वास्थ्य विशेषज्ञ से मिलें।",
      Severe: "आपका स्कोर गंभीर स्तर का डिप्रेशन दिखाता है। कृपया इसे नज़रअंदाज़ न करें — किसी योग्य मानसिक स्वास्थ्य विशेषज्ञ या डॉक्टर से जल्द से जल्द मिलें।",
    },
  },
};

const expressionMeta = {
  neutral: { en: "Neutral", hi: "सामान्य", emoji: "🙂" },
  happy: { en: "Happy", hi: "खुश", emoji: "😊" },
  sad: { en: "Sad", hi: "उदास", emoji: "😔" },
  angry: { en: "Angry", hi: "गुस्सा", emoji: "😠" },
  fearful: { en: "Fearful", hi: "डरा हुआ", emoji: "😨" },
  disgusted: { en: "Disgusted", hi: "नापसंदगी", emoji: "😖" },
  surprised: { en: "Surprised", hi: "हैरान", emoji: "😮" },
};

const expressionOrder = ["neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised"];

const voiceKeywords = {
  en: {
    0: ["not at all", "never happens", "never", "none", "nope", "not really", "zero", "no", "one"],
    1: ["several days", "some days", "a few days", "a little", "occasionally", "sometimes", "rarely", "two"],
    2: ["more than half", "most days", "quite often", "frequent", "often", "three"],
    3: ["nearly every day", "almost always", "all the time", "constantly", "every day", "everyday", "always", "four"],
  },
  hi: {
    0: ["बिल्कुल नहीं", "कभी नहीं", "नहीं", "नही", "ना", "शून्य", "जीरो", "एक"],
    1: ["कुछ दिन", "थोड़े दिन", "कभी-कभी", "कभी कभी", "एक दिन", "दो दिन", "थोड़ा", "थोड़ी", "दो"],
    2: ["आधे से ज़्यादा", "ज़्यादातर दिन", "बहुत बार", "ज़्यादातर", "ज्यादातर", "अक्सर", "आधे", "आधा", "तीन"],
    3: ["लगभग हर दिन", "बहुत ज़्यादा", "बहुत ज्यादा", "हमेशा ही", "रोज़ रोज़", "हर दिन", "हमेशा", "निरंतर", "रोज़", "रोज", "चार"],
  },
};

const yesWords = {
  en: ["yes", "yeah", "yep", "correct", "right", "sure", "confirm"],
  hi: ["हाँ", "हां", "जी हाँ", "जी", "सही है", "सही"],
};

const noWords = {
  en: ["no", "nope", "wrong", "incorrect", "redo"],
  hi: ["नहीं", "नही", "ना", "गलत"],
};

const crisisHelplines = {
  en: ["Positive Mind Care Helpline — 089205 30832", "iCall (TISS) — 9152987821 (Mon-Sat, 8am-10pm)"],
  hi: ["Positive Mind Care हेल्पलाइन — 089205 30832", "iCall (TISS) — 9152987821 (सोम-शनि, 8am-10pm)"],
};


const contact = { whatsapp: "918920775098", email: "contact@positivemindcare.com", org: "Positive Mind Care" };

const doctors = [
  { name: "Ms. Sakshi Saini", speciality: "Clinical Psychologist", experience: "3 Years", fee: "₹1500", duration: "30 mins", slot: "Available today", url: "https://positivemindcare.com/portal/experts/dr-sakshi-saini-Po33", image: "https://forestgreen-scorpion-490773.hostingersite.com/wp-content/uploads/2026/09/IMG_20260906_193228.jpg" },
  { name: "Dr. Rahul Yadav", speciality: "Psychiatrist (Deep TMS Expert)", experience: "10 Years", fee: "₹1500", duration: "30 mins", slot: "Available today", url: "https://positivemindcare.com/portal/experts/dr-rahul-yadav-4zx2", image: "https://forestgreen-scorpion-490773.hostingersite.com/wp-content/uploads/2026/08/Rahul-Yadav.webp" },
];

const confirmIndices = [0, 6];

const maxScore = { anxiety: 21, depression: 27 };

function bandFor(kind, score) {
  const rows = bandScale[kind];
  return (rows.find((row) => score <= row.upTo) || rows[rows.length - 1]).band;
}

function bandRowsFor(kind) {
  return bandScale[kind].map((row, i) => ({ range: `${i === 0 ? 0 : bandScale[kind][i - 1].upTo + 1}-${row.upTo}`, band: row.band }));
}

function bucketFor(band) {
  if (band === "Severe" || band === "Moderately severe") return "high";
  if (band === "Moderate") return "moderate";
  if (band === "Mild") return "mild";
  return "low";
}

function parseVoiceAnswer(transcript, lang) {
  const text = transcript.trim().toLowerCase();
  let best = null;
  let bestLength = -1;
  for (const [value, words] of Object.entries(voiceKeywords[lang])) {
    for (const word of words) {
      const needle = word.toLowerCase();
      if (text.includes(needle) && needle.length > bestLength) { best = Number(value); bestLength = needle.length; }
    }
  }
  return best;
}

function parseYesNo(transcript, lang) {
  const text = transcript.trim().toLowerCase();
  if (noWords[lang].some((word) => text.includes(word))) return false;
  if (yesWords[lang].some((word) => text.includes(word))) return true;
  return null;
}

function expressionDistribution(sums, frames) {
  if (frames === 0) return [];
  return expressionOrder
    .map((key) => ({ key, pct: Math.round(((sums[key] || 0) / frames) * 100) }))
    .sort((a, b) => b.pct - a.pct);
}

return {
  questions, labels, bandScale, bandHi, bandEmoji, solutions, bandExplanations, expressionMeta, expressionOrder,
  crisisHelplines, contact, doctors, confirmIndices, maxScore,
  bandFor, bandRowsFor, bucketFor, parseVoiceAnswer, parseYesNo, expressionDistribution,
};
})();
