# Draft cockpit

`index.html` is a single self-contained page: no server, no build step, no
network. It ships with synthetic demo data embedded so it works the moment you
open it.

## Using it for a real draft

```bash
python3 -m ffdraft.cli export -o cockpit_data.json
```
Open `index.html` on your phone, tap **Load export**, pick that file. From then
on everything runs locally — which matters, because draft-room wifi is bad and
you cannot afford a spinner while the clock runs.

## What recomputes live

Marking a player **Mine** or **Gone** re-runs the Monte Carlo in your browser:
survival probability, positional fallback value, expected regret, and the
resulting order. Replacement level and VORP come from the snapshot and stay
fixed for the session.

Marks persist in `localStorage` on that device only, and survive a reload.

## Regenerating the embedded demo data

`index.html` carries its demo dataset inline so it works offline. To rebuild
that block after changing the synthetic pool:

```bash
python3 cockpit/build.py
```

It rewrites only the `<script id="seedData">` element and leaves the page alone.
