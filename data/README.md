# Real-cabinet data (not in git)

Emerson's drawing set and photos are for hackathon use only and must not be published, so `data/emerson/` is git-ignored.
Put the files there locally (or mount the folder into the engine container at `/app/data/emerson`):

```
data/emerson/Sanitized_Cabinet_Drawing.pdf
data/emerson/IMG_20260726_122659228_HDR.jpg   # front, upper shelf: PS11-PS23, D13/D23, DS11-DS22
data/emerson/IMG_20260726_122705466_HDR.jpg   # front, lower area: CHARM carriers 13CSLS03334/35, baseplates, TERM1F, SB..
data/emerson/IMG_20260726_122716037_HDR.jpg   # front, whole cabinet (door open)
data/emerson/IMG_20260726_122949440_HDR.jpg   # left side close-up: DS1/XP11, CB11-CB16, XG11, ferrules (+ PS11)
data/emerson/IMG_20260726_123455538_HDR.jpg   # rear: CHARM columns 13CSLS03331-33, 331/332/333CBP..
data/emerson/ground_truth.json                # hand-made answer key per photo (eval_real.py)
data/emerson/forged/                          # planted-fault variants + answer_key.json (python forge_real.py)
```

The engine finds them through `EAGLE_EYE_REAL_DATA` (default: this folder). When they are present the console offers the
"Emerson 13GE03331" preset; when they are absent everything else still works.
