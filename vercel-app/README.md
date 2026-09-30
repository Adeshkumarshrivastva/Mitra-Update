# MITRA on Vercel (serverless)

Free-tier friendly version of MITRA. No always-on server: the browser listens (speech recognition) and speaks
(speech synthesis), and small Python functions in `api/` do login and the replies.

## Deploy
1. Vercel -> Add New Project -> import this GitHub repo.
2. **Root Directory: `vercel-app`**
3. Framework Preset: **Other**. Build Command: **leave empty**. Output Directory: leave as is (`vercel.json` sets `public`).
4. Environment Variables:
   - `GEMINI_API_KEY` (required)
   - `MITRA_LOGIN_PIN` (default 1234)
   - `SESSION_SECRET` (any long random text)
   - `GEMINI_MODEL` (optional)
5. Deploy. Open the site in Chrome or Edge over https and allow the mic.

## Notes
- `api/_lib/companion.py` and `api/_lib/llm_gemini.py` are copies of `../app/companion.py` and `../app/llm_gemini.py`.
  If you change the Hindi replies or the prompt there, copy the files here too.
- Mind Check results stay in the browser (localStorage); there is no database.
- Voice quality depends on the phone or browser's Hindi voice (Android Chrome and desktop Chrome have one).

## Run it on your laptop
```
cd vercel-app
python dev_server.py
```
Open http://localhost:3000 in Chrome, log in with your PIN and tap the mic. It reads `GEMINI_API_KEY` from the `.env` in
this folder or the parent folder. Nothing to install (Python 3.10+).
