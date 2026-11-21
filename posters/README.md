# City posters: photo sourcing

Run from this `posters/` folder on your own computer. The cloud session's network address is rate-limited by Wikimedia.

```bash
pip install pillow numpy
python3 tools/fetch_photos.py search     # ~5-10 min, finds licence-safe candidates
python3 tools/fetch_photos.py boats      # downloads boat candidates to work/boat_candidates/
python3 tools/fetch_photos.py download   # scores landmarks, top 8 per city to input/landmarks/candidates/<city>/
git add -A && git commit -m "Add candidate photos" && git push
```

Optional: set `UNSPLASH_ACCESS_KEY` / `PEXELS_API_KEY` before `search` to include those sources.
Then Claude reviews the candidates by eye, picks a winner per city, writes `input/credits.csv`,
`out/CREDITS.md` and the contact sheet `out/selection.jpg` for approval.
