#!/usr/bin/env python3
"""
tag_garments.py — Tag each scraped garment's attributes with FashionCLIP (local).

FashionCLIP (checkpoint: patrickjohncyh/fashion-clip) is a CLIP model fine-tuned on
fashion imagery. It's free and runs locally on CPU. We use it zero-shot: for each
attribute we score the product image against a fixed list of candidate labels and
take the best match plus a confidence (softmax probability within that attribute).

Attributes tagged per garment:
    garment_type, color, neckline, sleeve, pattern, fabric (a visual guess)

Signals are combined sensibly — each source does what it's best at:
    * garment_type — from the store's authoritative `product_type` field (a model
      photo often shows a full outfit, which fools image-only type classification);
      FashionCLIP is the fallback when product_type is missing.
    * color  — the store's declared Color option, normalised to a base colour
      (stores use marketing names like "Dotted Drift"); FashionCLIP fallback.
    * neckline / sleeve / pattern / fabric — FashionCLIP from the image. These are
      genuinely visual and usually absent from metadata, so this is where FashionCLIP
      earns its keep.

Low-confidence items (garment_type confidence below --threshold) are flagged
`needs_review: true`. A paid vision model could later resolve just those, but that
fallback is OFF and must not be enabled without explicit sign-off — this tool never
calls any external API.

ETHICS / SCOPE: garments only. We tag the CLOTHING in the image. No face detection,
no person identification, no identity stored. Any person in the photo is ignored.

Two input modes (same model, same attribute logic):
  * CATALOG (default):  .tmp/scraped_<date>.json   → .tmp/tagged_<date>.json
      garment_type/color come from store metadata; FashionCLIP fills the rest.
  * SOCIAL  (Instagram): .tmp/instagram_<date>.json → .tmp/tagged_social_<date>.json
      no store metadata, so ALL attributes (incl. garment_type/color) come from
      FashionCLIP off the post image. Auto-detected from the filename / `posts` key,
      or forced with --social. Social images are noisier than clean product shots,
      so expect lower confidence and more needs_review — that's expected and honest.

The input mode is auto-detected: a file named `instagram_*` or one whose JSON has a
top-level `posts` list is treated as social; otherwise catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
TMP = ROOT / ".tmp"
TODAY = str(date.today())

MODEL_NAME = "patrickjohncyh/fashion-clip"

# Candidate label sets per attribute. Tuned to Style Island's contemporary-Western
# womenswear vocabulary (see STYLE_ISLAND_PROFILE.md). Edit here to refine tagging.
ATTRIBUTES: dict[str, list[str]] = {
    "garment_type": [
        "dress", "maxi dress", "midi dress", "top", "blouse", "shirt", "t-shirt",
        "jumpsuit", "romper", "co-ord set", "trousers", "pants", "shorts", "skirt",
        "jacket", "blazer", "coat", "kaftan", "sweater", "cardigan",
    ],
    "color": [
        "white", "black", "beige", "cream", "brown", "tan", "grey", "navy blue",
        "blue", "light blue", "green", "olive green", "red", "maroon", "pink",
        "blush pink", "yellow", "orange", "purple", "lavender", "multicolour",
    ],
    "neckline": [
        "round neck", "v-neck", "collared neck", "square neck", "halter neck",
        "sweetheart neckline", "off-shoulder", "boat neck", "high neck", "scoop neck",
    ],
    "sleeve": [
        "sleeveless", "short sleeves", "long sleeves", "three-quarter sleeves",
        "puff sleeves", "cap sleeves", "strappy", "full sleeves",
    ],
    "pattern": [
        "solid colour", "floral print", "striped", "polka dot", "checked",
        "geometric print", "embroidered", "lace", "animal print", "tie-dye",
        "abstract print", "textured",
    ],
    "fabric": [
        "linen", "cotton", "satin", "silk", "denim", "chiffon", "georgette",
        "knit", "velvet", "crepe", "lace fabric",
    ],
}

PROMPT_TEMPLATE = "a photo of a garment, {}"   # FashionCLIP responds well to a short prompt

# Map a store's free-text product_type to our canonical garment_type vocabulary.
# Keyword-based so it's robust to casing and per-store naming ("TOP", "Shirts & Tops").
# Order matters: more specific keywords first.
_TYPE_KEYWORDS = [
    ("co-ord set", ("co-ord", "coord", "co ord", " set")),
    ("jumpsuit",   ("jumpsuit", "playsuit", "romper")),
    ("dress",      ("dress", "gown", "kaftan")),
    ("skirt",      ("skirt",)),
    ("shorts",     ("short",)),
    ("trousers",   ("pant", "trouser", "bottom", "legging")),
    ("jacket",     ("jacket", "blazer", "coat", "outerwear")),
    ("shirt",      ("shirt",)),
    ("top",        ("top", "blouse", "cami", "tee", "tank", "vest", "t-shirt")),
    ("sweater",    ("sweater", "cardigan", "knit", "pullover")),
]

# Base colours we recognise inside a store's free-text colour name.
_BASE_COLORS = [
    "white", "black", "beige", "cream", "ivory", "brown", "tan", "camel", "grey",
    "gray", "charcoal", "navy", "blue", "teal", "green", "olive", "sage", "red",
    "maroon", "burgundy", "wine", "pink", "blush", "rose", "peach", "yellow",
    "mustard", "orange", "rust", "purple", "lavender", "lilac", "mauve", "gold",
    "silver", "multicolour", "multicolor",
]


def normalise_type(product_type: str) -> str | None:
    """Map a store product_type to our canonical garment_type, or None if unknown."""
    t = (product_type or "").lower()
    if not t.strip():
        return None
    for canonical, keywords in _TYPE_KEYWORDS:
        if any(k in t for k in keywords):
            return canonical
    return None


def base_color_from(text: str) -> str | None:
    """Extract a recognised base colour from a store's free-text colour name."""
    t = (text or "").lower()
    for c in _BASE_COLORS:
        if c in t:
            return "multicolour" if c == "multicolor" else c
    return None


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def load_model():
    """Load FashionCLIP once. Imports are local so the rest of the pipeline can run
    without torch installed (e.g. just re-rendering a PDF)."""
    import torch
    from transformers import CLIPModel, CLIPProcessor

    print(f"Loading FashionCLIP ({MODEL_NAME}) — first run downloads ~600MB ...")
    model = CLIPModel.from_pretrained(MODEL_NAME)
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model.eval()
    return model, processor, torch


def _encode_label_texts(model, processor, torch):
    """Pre-encode every candidate label once (text features are image-independent).
    Returns {attr: (labels, normalized_text_features_tensor)}."""
    encoded = {}
    for attr, labels in ATTRIBUTES.items():
        prompts = [PROMPT_TEMPLATE.format(lbl) for lbl in labels]
        inputs = processor(text=prompts, return_tensors="pt", padding=True)
        with torch.no_grad():
            feats = model.get_text_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        encoded[attr] = (labels, feats)
    return encoded


def tag_image(image_path: Path, model, processor, torch, label_cache) -> dict:
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    with torch.no_grad():
        img_feat = model.get_image_features(**inputs)
    img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)

    result = {}
    for attr, (labels, text_feats) in label_cache.items():
        # cosine similarity → temperature-scaled softmax → top label + confidence
        sims = (img_feat @ text_feats.T).squeeze(0)
        probs = torch.softmax(sims * 100.0, dim=-1)
        top = int(torch.argmax(probs))
        result[attr] = labels[top]
        result[f"{attr}_confidence"] = round(float(probs[top]), 3)
    return result


# ---------------------------------------------------------------------------
# Tag one record (works for a catalog product OR a social post)
# ---------------------------------------------------------------------------

def tag_record(rec: dict, model, processor, torch, label_cache, threshold: float,
               *, product_type: str | None, declared_color: str | None) -> bool:
    """Tag a single record in place. Returns True if tagged, False if the image was
    missing. For social posts, pass product_type=None and declared_color=None so
    garment_type and color both come from FashionCLIP."""
    local = rec.get("image_local")
    if not local or not (ROOT / local).exists():
        rec["attributes"] = None
        rec["needs_review"] = True
        return False

    attrs = tag_image(ROOT / local, model, processor, torch, label_cache)

    # --- garment_type: authoritative product_type first, FashionCLIP fallback ---
    canonical = normalise_type(product_type or "")
    if canonical:
        garment_type, type_source = canonical, "product_type"
    else:
        garment_type, type_source = attrs["garment_type"], "fashionclip"

    # --- color: store's declared colour, normalised to a base; else FashionCLIP ---
    base = base_color_from(declared_color) if declared_color else None
    if base:
        color, color_source = base, "store"
    else:
        color, color_source = attrs["color"], "fashionclip"

    rec["attributes"] = {
        "garment_type": garment_type,
        "color":        color,
        "neckline":     attrs["neckline"],
        "sleeve":       attrs["sleeve"],
        "pattern":      attrs["pattern"],
        "fabric_guess": attrs["fabric"],
    }
    rec["attribute_sources"] = {
        "garment_type": type_source,
        "color":        color_source,
        "color_raw":    declared_color or "",
    }
    rec["attribute_confidence"] = {
        k: attrs[f"{k}_confidence"]
        for k in ("garment_type", "neckline", "sleeve", "pattern", "fabric")
    }
    # Flag for review only when garment_type leaned on FashionCLIP and it was unsure.
    rec["needs_review"] = (
        type_source == "fashionclip"
        and attrs["garment_type_confidence"] < threshold
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_input(arg_input: Path | None, social: bool) -> tuple[Path, bool]:
    """Pick the input file and decide catalog-vs-social mode."""
    if arg_input:
        is_social = social or arg_input.name.startswith("instagram") or \
            "posts" in json.loads(arg_input.read_text())
        return arg_input, is_social
    if social:
        files = sorted(TMP.glob("instagram_*.json"), reverse=True)
        if not files:
            print("ERROR: no instagram_*.json in .tmp/ — run scrape_instagram.py first.")
            sys.exit(1)
        return files[0], True
    files = sorted(TMP.glob("scraped_*.json"), reverse=True)
    if not files:
        print("ERROR: no scraped_*.json in .tmp/ — run scrape_catalog.py first.")
        sys.exit(1)
    return files[0], False


def main():
    parser = argparse.ArgumentParser(description="Tag garment attributes with FashionCLIP.")
    parser.add_argument("--input", type=Path,
                        help="scraped_<date>.json or instagram_<date>.json "
                             "(default: most recent of the chosen mode in .tmp/).")
    parser.add_argument("--social", action="store_true",
                        help="Tag Instagram posts (instagram_<date>.json) instead of a catalog.")
    parser.add_argument("--threshold", type=float, default=0.35,
                        help="garment_type confidence below this flags needs_review.")
    args = parser.parse_args()

    in_file, is_social = _resolve_input(args.input, args.social)
    print(f"Reading: {in_file}  (mode: {'SOCIAL' if is_social else 'catalog'})")
    data = json.loads(in_file.read_text())
    records = data.get("posts", []) if is_social else data.get("products", [])
    if not records:
        print("Nothing to tag (no records in input). Exiting.")
        return

    model, processor, torch = load_model()
    label_cache = _encode_label_texts(model, processor, torch)

    tagged, reviewed = 0, 0
    for i, rec in enumerate(records, 1):
        if is_social:
            ok = tag_record(rec, model, processor, torch, label_cache, args.threshold,
                            product_type=None, declared_color=None)
        else:
            ok = tag_record(rec, model, processor, torch, label_cache, args.threshold,
                            product_type=rec.get("product_type", ""),
                            declared_color=(rec.get("colors") or [None])[0])
        if ok:
            tagged += 1
            if rec.get("needs_review"):
                reviewed += 1
        if i % 20 == 0 or i == len(records):
            print(f"   tagged {i}/{len(records)}")

    date_stamp = data.get("scraped_date", TODAY)
    if is_social:
        out = {
            "scraped_date": date_stamp,
            "tagged_date":  TODAY,
            "model":        MODEL_NAME,
            "source":       "instagram",
            "posts":        records,
        }
        out_file = TMP / f"tagged_social_{date_stamp}.json"
    else:
        out = {
            "scraped_date": date_stamp,
            "tagged_date":  TODAY,
            "model":        MODEL_NAME,
            "stores":       data.get("stores", []),
            "products":     records,
        }
        out_file = TMP / f"tagged_{date_stamp}.json"
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\nDone — {tagged} tagged, {reviewed} low-confidence (needs_review).")
    print(f"Saved → {out_file}")


if __name__ == "__main__":
    main()
