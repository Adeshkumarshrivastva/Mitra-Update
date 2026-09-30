/* PDF report + certificate. Needs jsPDF (loaded from the CDN). The report is printed on the Positive Mind Care letterhead
   (header + footer images taken from "Original_Letter -Head.docx", stored in /assets). */
window.MCReport = (() => {
const { jsPDF } = window.jspdf;
const { bandExplanations, bandRowsFor, bandScale, bucketFor, contact, expressionMeta, labels, maxScore, questions, solutions } = window.MC;

function istStamp(iso) {
  const at = new Date(iso);
  // A record written before a field existed, or hand-edited storage, can hold junk here.
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata",
  }) + " IST";
}

function typeLabel(kind) {
  return kind === "depression" ? "PHQ-9 Depression" : "GAD-7 Anxiety";
}

// Lower is better on both scales. Returns null when there is no earlier check to compare with.
// pct is the share of the earlier score that was gained or lost; it is null when the earlier score was 0.
function progress(prevScore, score) {
  if (prevScore === undefined || prevScore === null) return null;
  if (score === prevScore) return { dir: "same", pct: 0 };
  const pct = prevScore > 0 ? Math.round((Math.abs(prevScore - score) / prevScore) * 100) : null;
  return { dir: score < prevScore ? "better" : "worse", pct };
}

function referenceNo(iso) {
  const stamp = new Date(iso).getTime();
  return `PMC-MC-${Number.isNaN(stamp) ? "000000" : stamp.toString(36).toUpperCase().slice(-6)}`;
}

const BAND_COLORS = {
  Minimal: [46, 158, 107],
  Mild: [155, 197, 61],
  Moderate: [240, 180, 41],
  "Moderately severe": [239, 138, 61],
  Severe: [214, 69, 65],
};
const BAND_MEANING = {
  Minimal: "Little or no symptoms",
  Mild: "Mild symptoms; self-care and monitoring",
  Moderate: "Symptoms affecting daily life; counselling advised",
  "Moderately severe": "Significant symptoms; professional support advised",
  Severe: "Severe symptoms; prompt professional help advised",
};
const TIER_LABEL = { urgent: "Urgent help needed", elevated: "Needs attention", normal: "Normal" };

const GREEN = [58, 84, 70];
const INK = [28, 36, 32];
const GREY = [110, 118, 114];
const LIGHT = [244, 247, 245];
const LINE = [214, 223, 218];

// Aspect ratios of the two letterhead images (from the Word template).
const HEADER_RATIO = 7764145 / 1341120;
const FOOTER_RATIO = 7726680 / 1177925;
const PAGE_WIDTH = 210;
const A4_HEIGHT = 297;
const MEASURE_HEIGHT = 4000; // tall scratch page used only to measure how long the content is
const LETTERHEAD_URLS = { header: "/assets/letterhead-header.jpeg", footer: "/assets/letterhead-footer.jpeg" };

function toDataUrl(url) {
  return fetch(url)
    .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.blob(); })
    .then((blob) => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    }));
}

let letterheadPromise = null;
function loadLetterhead() {
  if (!letterheadPromise) {
    letterheadPromise = Promise.all([toDataUrl(LETTERHEAD_URLS.header), toDataUrl(LETTERHEAD_URLS.footer)])
      .then(([header, footer]) => ({ header, footer }))
      .catch(() => { letterheadPromise = null; return null; });
  }
  return letterheadPromise;
}

/* The report is always written in English: jsPDF's built-in fonts carry no Devanagari
   glyphs, so a Hindi PDF would render as blank boxes. The on-screen result stays bilingual. */
// One single page: one letterhead header at the top, one footer at the bottom, and the whole report in between.
// The page is as tall as the content needs (at least A4), so nothing is split over several pages with repeated headers.
async function buildReport(data) {
  const letterhead = await loadLetterhead();
  const footerHeight = PAGE_WIDTH / FOOTER_RATIO;
  const measured = composeReport(data, letterhead, MEASURE_HEIGHT);
  const height = Math.max(A4_HEIGHT, Math.ceil(measured.endY + footerHeight + 8));
  return composeReport(data, letterhead, height).pdf;
}

function composeReport(data, letterhead, H) {
  const W = PAGE_WIDTH;
  const pdf = new jsPDF({ unit: "mm", format: [W, H] });
  const left = 16;
  const right = 194;
  const width = right - left;
  const headerH = W / HEADER_RATIO;
  const footerH = W / FOOTER_RATIO;
  const top = letterhead ? headerH + 8 : 20;
  let y = top;

  const decorate = () => {
    if (!letterhead) return;
    pdf.addImage(letterhead.header, "JPEG", 0, 0, W, headerH);
    pdf.addImage(letterhead.footer, "JPEG", 0, H - footerH, W, footerH);
  };
  const heading = (text) => {
    y += 3;
    pdf.setFillColor(...GREEN).rect(left, y - 3.6, 1.6, 5, "F");
    pdf.setFont("helvetica", "bold").setFontSize(10.5).setTextColor(...GREEN);
    pdf.text(text.toUpperCase(), left + 4, y);
    y += 5;
  };
  const body = (text, size = 9.5, colour = INK) => {
    pdf.setFont("helvetica", "normal").setFontSize(size).setTextColor(...colour);
    for (const line of pdf.splitTextToSize(text, width)) {
      pdf.text(line, left, y);
      y += size * 0.5;
    }
    y += 2;
  };
  const bullet = (text) => {
    pdf.setFont("helvetica", "normal").setFontSize(9.5).setTextColor(...INK);
    const lines = pdf.splitTextToSize(text, width - 6);
    pdf.text("•", left + 1, y);
    for (const line of lines) { pdf.text(line, left + 6, y); y += 4.8; }
    y += 1;
  };

  decorate();

  const max = maxScore[data.kind];
  const bucket = bucketFor(data.band);
  const bandColour = BAND_COLORS[data.band] || GREEN;
  const label = typeLabel(data.kind);

  // ---- title
  pdf.setFont("helvetica", "bold").setFontSize(15).setTextColor(...GREEN);
  pdf.text("MENTAL WELLNESS SCREENING REPORT", left, y + 2);
  pdf.setFont("helvetica", "normal").setFontSize(9).setTextColor(...GREY);
  pdf.text(`${label}  |  Confidential`, left, y + 8);
  pdf.text(`Ref: ${referenceNo(data.createdAt)}`, right, y + 2, { align: "right" });
  pdf.text(istStamp(data.createdAt), right, y + 8, { align: "right" });
  y += 13;

  // ---- participant details
  const cells = [
    ["Name", data.name || "Participant"], ["Mobile", data.mobile || "—"],
    ["Email", data.email || "—"], ["Instrument", label],
  ];
  const rowH = 12;
  pdf.setFillColor(...LIGHT).setDrawColor(...LINE).setLineWidth(0.3).roundedRect(left, y, width, rowH * 2, 1.5, 1.5, "FD");
  cells.forEach(([key, value], i) => {
    const cx = left + 4 + (i % 2) * (width / 2);
    const cy = y + Math.floor(i / 2) * rowH + 4.5;
    pdf.setFont("helvetica", "normal").setFontSize(7.5).setTextColor(...GREY).text(key.toUpperCase(), cx, cy);
    pdf.setFont("helvetica", "bold").setFontSize(10).setTextColor(...INK).text(String(value), cx, cy + 4.6);
  });
  y += rowH * 2 + 6;

  // ---- result panel with the score scale
  const panelH = 58;
  pdf.setFillColor(255, 255, 255).setDrawColor(...LINE).setLineWidth(0.3).roundedRect(left, y, width, panelH, 1.5, 1.5, "FD");
  pdf.setFillColor(...bandColour).rect(left, y, 2.2, panelH, "F");
  pdf.setFont("helvetica", "normal").setFontSize(7.5).setTextColor(...GREY).text("TOTAL SCORE", left + 8, y + 7);
  pdf.setFont("helvetica", "bold").setFontSize(30).setTextColor(...INK).text(String(data.score), left + 8, y + 20);
  const scoreWidth = pdf.getTextWidth(String(data.score));
  pdf.setFont("helvetica", "normal").setFontSize(13).setTextColor(...GREY).text(`/ ${max}`, left + 10 + scoreWidth, y + 20);

  const pillText = data.band.toUpperCase();
  pdf.setFont("helvetica", "bold").setFontSize(10);
  const pillW = pdf.getTextWidth(pillText) + 10;
  pdf.setFillColor(...bandColour).roundedRect(right - pillW - 5, y + 6, pillW, 8, 4, 4, "F");
  pdf.setTextColor(255, 255, 255).text(pillText, right - pillW / 2 - 5, y + 11.4, { align: "center" });
  if (data.tier) {
    pdf.setFont("helvetica", "normal").setFontSize(8.5).setTextColor(...GREY);
    pdf.text(`Priority: ${TIER_LABEL[data.tier] || data.tier}`, right - 5, y + 19.5, { align: "right" });
  }

  // scale: one coloured segment per band, proportional to the number of possible scores in it
  const scaleLeft = left + 8;
  const scaleWidth = width - 16;
  const barY = y + 33;
  const total = max + 1;
  let start = 0;
  bandScale[data.kind].forEach((row) => {
    const count = row.upTo - start + 1;
    const x = scaleLeft + (start / total) * scaleWidth;
    const w = (count / total) * scaleWidth;
    pdf.setFillColor(...BAND_COLORS[row.band]).rect(x, barY, w - 0.4, 6, "F");
    pdf.setFont("helvetica", "bold").setFontSize(7.5).setTextColor(...INK).text(`${start}-${row.upTo}`, x + w / 2, barY + 10.5, { align: "center" });
    pdf.setFont("helvetica", "normal").setFontSize(6.5).setTextColor(...GREY).text(row.band, x + w / 2, barY + 14.5, { align: "center" });
    start = row.upTo + 1;
  });
  const markerX = scaleLeft + ((data.score + 0.5) / total) * scaleWidth;
  pdf.setFillColor(...INK).triangle(markerX - 2.4, barY - 4, markerX + 2.4, barY - 4, markerX, barY - 0.4, "F");
  pdf.setFont("helvetica", "bold").setFontSize(8).setTextColor(...INK).text(`Your score: ${data.score}`, Math.min(Math.max(markerX, scaleLeft + 14), scaleLeft + scaleWidth - 14), barY - 6, { align: "center" });
  y += panelH + 6;

  // ---- severity table
  heading("Score ranges and what they mean");
  pdf.setFillColor(...GREEN).rect(left, y, width, 6.5, "F");
  pdf.setFont("helvetica", "bold").setFontSize(8.5).setTextColor(255, 255, 255);
  pdf.text("Score", left + 3, y + 4.4);
  pdf.text("Category", left + 26, y + 4.4);
  pdf.text("What it usually means", left + 74, y + 4.4);
  y += 6.5;
  for (const { range, band } of bandRowsFor(data.kind)) {
    // Exact match, not a prefix one: "Moderately severe" also starts with "Moderate".
    const mine = band === data.band;
    if (mine) pdf.setFillColor(233, 244, 238).rect(left, y, width, 7, "F");
    pdf.setDrawColor(...LINE).setLineWidth(0.2).line(left, y + 7, right, y + 7);
    pdf.setFillColor(...BAND_COLORS[band]).circle(left + 5, y + 3.5, 1.5, "F");
    pdf.setFont("helvetica", mine ? "bold" : "normal").setFontSize(9).setTextColor(...INK);
    pdf.text(range, left + 9, y + 4.6);
    pdf.text(band, left + 26, y + 4.6);
    pdf.setFont("helvetica", "normal").setTextColor(...(mine ? INK : GREY)).text(BAND_MEANING[band], left + 74, y + 4.6);
    if (mine) pdf.setFont("helvetica", "bold").setTextColor(...GREEN).text("< your score", right - 2, y + 4.6, { align: "right" });
    y += 7;
  }
  y += 3;

  // ---- interpretation
  heading("Interpretation");
  body(`Your score of ${data.score}/${max} falls in the ${data.band.toLowerCase()} range. ${bandExplanations.en[data.kind][data.band] || ""}`);

  // ---- every question and the option that was chosen
  if (Array.isArray(data.answers) && data.answers.length) {
    heading("Your answers");
    body("The option chosen for each question (A to D, the selected one is filled).", 8.5, GREY);
    questions[data.kind].forEach((question, i) => {
      const value = data.answers[i];
      const lines = pdf.splitTextToSize(question.en, 118);
      const rowHeight = Math.max(lines.length * 4.4 + 6.5, 11);
      pdf.setDrawColor(...LINE).setLineWidth(0.2).line(left, y + rowHeight - 1.5, right, y + rowHeight - 1.5);
      pdf.setFont("helvetica", "bold").setFontSize(9).setTextColor(...GREEN).text(`Q${i + 1}`, left, y + 3.6);
      pdf.setFont("helvetica", "normal").setFontSize(9).setTextColor(...INK).text(lines, left + 9, y + 3.6);
      const chosen = value === undefined || value === null ? "-" : `${String.fromCharCode(65 + value)}. ${labels.en[value]}`;
      pdf.setFontSize(8).setTextColor(...GREY).text(`Chosen: ${chosen}`, left + 9, y + lines.length * 4.4 + 3);
      for (let option = 0; option < 4; option += 1) {
        const bx = right - 4 * 8 + option * 8;
        const on = option === value;
        pdf.setFillColor(...(on ? GREEN : LIGHT)).setDrawColor(...(on ? GREEN : LINE)).roundedRect(bx, y + 0.6, 6.4, 6.4, 1, 1, "FD");
        pdf.setFont("helvetica", "bold").setFontSize(8).setTextColor(...(on ? [255, 255, 255] : GREY)).text(String.fromCharCode(65 + option), bx + 3.2, y + 4.9, { align: "center" });
      }
      y += rowHeight;
    });
    y += 2;
  }

  // ---- key observations
  const notes = [];
  const change = progress(data.prevScore, data.score);
  if (change) {
    const when = data.prevAt ? ` on ${new Date(data.prevAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : "";
    const outcome = change.dir === "same" ? "no change"
      : `${change.dir === "better" ? "an improvement" : "an increase in symptoms"}${change.pct === null ? "" : ` of ${change.pct}%`}`;
    notes.push(`Compared with the previous ${label} screening${when}: score ${data.prevScore} (${data.prevBand || "-"}) to ${data.score} (${data.band}), ${outcome}.`);
  }
  if (data.insightText) notes.push(data.insightText);
  if (data.followUpAt) notes.push(`Next screening advised on: ${new Date(data.followUpAt).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}.`);
  if (data.safetyText) notes.push(`Driving safety: ${data.safetyText}`);
  if (notes.length) {
    heading("Key observations");
    notes.forEach(bullet);
  }

  if (data.distribution && data.distribution.length > 0) {
    heading("Facial expression observation");
    body(`During the screening the camera most often read a ${(data.dominant || "neutral").toLowerCase()} expression. Facial expression is one extra behavioural data point and is best interpreted alongside, not instead of, your self-reported answers. Average distribution across the whole session:`);
    for (const row of data.distribution) {
      const meta = expressionMeta[row.key];
      pdf.setFont("helvetica", "normal").setFontSize(9).setTextColor(...INK);
      pdf.text(meta ? meta.en : row.key, left, y);
      pdf.setFillColor(226, 232, 228).rect(left + 34, y - 3, 90, 3.6, "F");
      pdf.setFillColor(...GREEN).rect(left + 34, y - 3, Math.max(0.6, (row.pct / 100) * 90), 3.6, "F");
      pdf.text(`${row.pct}%`, left + 128, y);
      y += 5.6;
    }
    y += 2;
  }

  heading("Recommendations");
  solutions.en[bucket].forEach(bullet);

  if (data.selfHarm) {
    heading("Immediate support");
    body("You reported thoughts of being better off dead or of hurting yourself. Please treat this as urgent. Positive Mind Care Helpline: 089205 30832. iCall (TISS): 9152987821, Mon-Sat 8am-10pm. If you feel at immediate risk, contact someone you trust or your local emergency service now.");
  }

  heading("Please note");
  body("This is a screening result, not a clinical diagnosis. Screening tools indicate the likelihood that a further conversation would be useful; they cannot confirm or rule out a condition. If your score rises, your symptoms persist, or you would simply like support, consulting a qualified mental health professional is strongly recommended.", 8.5, GREY);

  // ---- signature line
  y += 8;
  pdf.setDrawColor(...GREY).setLineWidth(0.3).line(right - 58, y, right, y);
  pdf.setFont("helvetica", "bold").setFontSize(9).setTextColor(...INK).text("Positive Mind Care and Research Centre", right, y + 5, { align: "right" });
  pdf.setFont("helvetica", "normal").setFontSize(8).setTextColor(...GREY).text("Automated screening report (Mind Check)", right, y + 9.5, { align: "right" });

  y += 14;
  pdf.setFont("helvetica", "normal").setFontSize(7.5).setTextColor(...GREY);
  pdf.text(`Ref ${referenceNo(data.createdAt)}`, left, H - footerH - 3);

  return { pdf, endY: y };
}

function buildCertificate(data) {
  const pdf = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
  const centre = 148.5;
  pdf.setFillColor(255, 253, 248).rect(0, 0, 297, 210, "F");
  pdf.setDrawColor(...GREEN).setLineWidth(1.6).rect(12, 12, 273, 186);
  pdf.setLineWidth(0.3).rect(16, 16, 265, 178);

  pdf.setFont("helvetica", "normal").setFontSize(11).setTextColor(...GREY);
  pdf.text(contact.org.toUpperCase(), centre, 36, { align: "center" });
  pdf.setFont("helvetica", "bold").setFontSize(28).setTextColor(...GREEN);
  pdf.text("Mental Health Awareness Certificate", centre, 58, { align: "center" });
  pdf.setFont("helvetica", "normal").setFontSize(12).setTextColor(...GREY);
  pdf.text("This is to recognise that", centre, 78, { align: "center" });

  pdf.setFont("helvetica", "bold").setFontSize(24).setTextColor(...INK);
  pdf.text(data.name || "Participant", centre, 95, { align: "center" });
  pdf.setDrawColor(...GREEN).setLineWidth(0.5).line(centre - 45, 100, centre + 45, 100);

  pdf.setFont("helvetica", "normal").setFontSize(13).setTextColor(...INK);
  pdf.text("took a step today towards understanding and caring for their mental health", centre, 116, { align: "center" });
  pdf.text(`by completing the ${typeLabel(data.kind)} screening.`, centre, 125, { align: "center" });

  pdf.setFont("helvetica", "bold").setFontSize(12).setTextColor(...GREEN);
  pdf.text(`${data.score} / ${maxScore[data.kind]} — ${data.band}`, centre, 143, { align: "center" });

  pdf.setFont("helvetica", "normal").setFontSize(10).setTextColor(...GREY);
  pdf.text(istStamp(data.createdAt), centre, 168, { align: "center" });
  pdf.text("Screening for awareness, not a clinical diagnosis.", centre, 176, { align: "center" });
  return pdf;
}

return { buildReport, buildCertificate, istStamp, typeLabel, referenceNo, progress, loadLetterhead, BAND_COLORS, TIER_LABEL };
})();
