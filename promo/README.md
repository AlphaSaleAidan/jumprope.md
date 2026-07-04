# Promo assets

Launch / social assets for Jumping Rope. All rendered from code (HTML/CSS/JS →
headless Chrome → ffmpeg) — no stock footage, no AI-video credits.

| File | What | Use |
|------|------|-----|
| `launch.html` | The launch animation, self-contained. Autoplays, loops, scales to any screen. Click to restart. | Open in a browser; host on GitHub Pages for a live link. |
| `launch.mp4` | 1080×1920, ~34s render of `launch.html`. | Instagram Reels / TikTok / Shorts upload (they can't post an HTML page). Import into an editor (e.g. Palmier Pro) to refine. |
| `memes/meme1.png` | "Semantic search trying to find the one `close()` you meant" — conspiracy-board style. | Social post. |
| `memes/meme2.png` | Galaxy-brain: keyword → meaning → **exact key**. | Social post. |

The lower third of `launch.html` / `launch.mp4` is intentionally kept clear (with
a subtle darkening) so a creator's head-and-shoulders talking-head sits cleanly
over the bottom for a reaction/voiceover cut.

**On the memes:** these are **original artwork** in the spirit of the classic
"conspiracy board" and "galaxy brain" formats — not copyrighted stills — so
they're safe to ship in a public repo. The `.html` sources are included; edit the
captions and re-render.

## Re-render

```bash
# from the video working dir (has puppeteer-core installed)
node render-all.mjs        # launch.html → frames/ → then ffmpeg to launch.mp4
node shoot-meme.mjs        # meme*.html → meme*.png
```
