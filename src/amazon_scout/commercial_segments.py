from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


COMMERCIAL_SEGMENT_STATUSES = {"COMPARABLE", "ADJACENT", "NON_COMPARABLE", "UNKNOWN"}


@dataclass(frozen=True)
class PriceGateDecision:
    gate: bool
    reason: str
    sample_size: int
    median_price_aed: float | None
    in_target_band_count: int
    in_target_band_ratio: float | None
    minimum_sample_size: int
    minimum_in_target_band_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TargetCommercialProfile:
    product_subtype: str
    required_features: tuple[str, ...] = ()
    preferred_features: tuple[str, ...] = ()
    allowed_pack_counts: tuple[int, ...] = ()
    size_requirement: str = "UNKNOWN"
    allowed_materials: tuple[str, ...] = ()
    excluded_subtypes: tuple[str, ...] = ()
    target_positioning: str = "MID_MARKET"
    specific: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_commercial_config(path: str | Path = "config/commercial_segments.yaml") -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_price_gate(comparable_prices_aed: list[float], minimum_price_aed: float | None, maximum_price_aed: float | None, *, minimum_sample_size: int, minimum_in_target_band_ratio: float) -> PriceGateDecision:
    """Return the one canonical V1.2.3 comparable-market price decision."""
    from statistics import median

    prices = [float(value) for value in comparable_prices_aed]
    sample_size = len(prices); midpoint = median(prices) if prices else None
    in_band = sum((minimum_price_aed is None or value >= minimum_price_aed) and (maximum_price_aed is None or value <= maximum_price_aed) for value in prices)
    ratio = in_band / sample_size if sample_size else None
    enough = sample_size >= minimum_sample_size
    median_in_band = midpoint is not None and (minimum_price_aed is None or midpoint >= minimum_price_aed) and (maximum_price_aed is None or midpoint <= maximum_price_aed)
    gate = enough and (median_in_band or (ratio is not None and ratio >= minimum_in_target_band_ratio))
    if not enough: reason = f"Only {sample_size} current comparable Amazon UAE products were observed; at least {minimum_sample_size} are required."
    elif gate: reason = f"Comparable commercial segment satisfies the requested range (median AED {midpoint:.2f}; in-band {ratio:.0%})."
    else: reason = f"Comparable segment median AED {midpoint:.2f} and in-band ratio {ratio:.0%} do not satisfy the AED {minimum_price_aed}–{maximum_price_aed} rule."
    return PriceGateDecision(gate, reason, sample_size, midpoint, in_band, ratio, minimum_sample_size, minimum_in_target_band_ratio)


def target_commercial_profile(niche: str, keyword: str) -> TargetCommercialProfile:
    text = f"{niche} {keyword}".lower()
    if "packing cube" in text:
        return TargetCommercialProfile("compression_packing_cubes", ("compression",), ("expandable",), tuple(range(4, 9)), "MULTI_PIECE_SET", ("fabric",), ("ordinary_packing_cubes", "single_bag", "shoe_bag"), "MID_PREMIUM")
    if "desk mat" in text or "desk pad" in text:
        return TargetCommercialProfile("fabric_desk_mat", ("fabric_surface", "desk_size"), ("stitched_edge",), (), "DESK_SIZE", ("felt", "cloth", "fabric"), ("tiny_mouse_pad", "hard_desk_pad", "rgb_electronic_mat", "leather_desk_mat"), "MID_PREMIUM")
    if ("pet" in text or "dog" in text or "cat" in text) and ("feed" in text or "food" in text) and "mat" in text:
        sized = any(token in text for token in ("large", "xl", "extra large"))
        return TargetCommercialProfile("pet_feeding_mat", ("raised_edge", "large_or_xl", "single_pack") if sized else (), ("silicone",), (1,) if sized else (), "LARGE_XL" if sized else "ANY", ("silicone", "rubber"), ("lick_mat", "litter_only_mat"), "MID_PREMIUM", sized)
    return TargetCommercialProfile("generic", (), (), (), "UNKNOWN", (), (), "MID_MARKET", False)


def _pack_count(text: str) -> int | None:
    patterns = (
        r"\b(?:set\s+of|pack\s+of)\s*(\d{1,2})\b", r"\b(\d{1,2})\s*[- ]?(?:pcs?|pieces?|pack|set)\b",
        r"\b(\d{1,2})\s*in\s*1\b", r"\b(1)\s*pcs?\b",
    )
    values = [int(match.group(1)) for pattern in patterns for match in re.finditer(pattern, text)]
    return max(values) if values else None


def _dimensions(text: str) -> list[dict[str, float | str]]:
    found: list[dict[str, float | str]] = []
    for match in re.finditer(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:x|×|\*)\s*(\d{1,3}(?:\.\d+)?)\s*(cm|inches?|in|\")?", text):
        unit = (match.group(3) or "UNKNOWN").replace('"', "in").lower()
        found.append({"length": float(match.group(1)), "width": float(match.group(2)), "unit": unit})
    return found


def _desk_sized(dimensions: list[dict[str, float | str]], text: str) -> bool | None:
    if any(token in text for token in ("xxl", "extended", "large desk", "desk mat", "desk pad", "keyboard")):
        return True
    for item in dimensions:
        length = float(item["length"]); width = float(item["width"]); unit = item["unit"]
        if unit == "cm" and max(length, width) >= 60 and min(length, width) >= 25: return True
        if unit in {"in", "inch", "inches"} and max(length, width) >= 24 and min(length, width) >= 10: return True
    return None


def derive_segment_attributes(result: dict[str, Any]) -> dict[str, Any]:
    title = str(result.get("title") or ""); text = title.lower(); dimensions = _dimensions(text)
    pack = _pack_count(text)
    material = next((name for name in ("silicone", "rubber", "felt", "fabric", "cloth", "leather", "cork", "polyester", "mesh") if name in text), None)
    features = sorted(name for name, terms in {
        "compression": ("compression", "compressible", "compressable"), "expandable": ("expandable", "expansion"),
        "raised_edge": ("raised edge", "raised edges", "raised lip", "high lip", "high-lip", "with edges", "residue collection pocket"),
        "stitched_edge": ("stitched edge", "stitched edges", "stitched edging"), "rgb_electronic": ("rgb", "led", "wireless charging"),
        "fabric_surface": ("felt", "fabric", "cloth", "micro-weave", "mousepad", "mouse pad"),
    }.items() if any(term in text for term in terms))
    size_class = "XL" if any(term in text for term in ("extra large", "xxl", " x-large", " xl ")) else "LARGE" if "large" in text else "SMALL" if "small" in text else "UNKNOWN"
    if dimensions:
        largest = max(float(x["length"]) for x in dimensions); unit = dimensions[0]["unit"]
        if (unit == "cm" and largest >= 60) or (unit in {"in", "inch", "inches"} and largest >= 24): size_class = "XL"
        elif (unit == "cm" and largest >= 45) or (unit in {"in", "inch", "inches"} and largest >= 18): size_class = "LARGE"
        elif unit != "UNKNOWN": size_class = "SMALL"
    brand = str(result.get("brand") or "").strip().lower()
    brand_tier = "PREMIUM_BRAND" if brand in {"logitech", "satechi", "petlibro", "tripped", "bagsmart"} or any(x in text for x in ("logitech", "satechi", "petlibro", "tripped", "bagsmart")) else "UNBRANDED_OR_MIDMARKET"
    positioning = "PREMIUM" if brand_tier == "PREMIUM_BRAND" or any(x in text for x in ("premium", "heavy duty", "ykk", "vegan-leather")) else "BASIC" if any(x in text for x in ("basic", "simple")) else "MID_MARKET"
    subtype = "UNKNOWN"
    if "packing cube" in text:
        subtype = "compression_packing_cubes" if "compression" in features else "ordinary_packing_cubes"
        if pack == 1 or ("cube" in text and pack is None and "set" not in text): subtype = "single_bag"
    elif ("feeding mat" in text or "food mat" in text or "bowl mat" in text or "placemat" in text) and "lick mat" not in text: subtype = "pet_feeding_mat"
    elif "lick mat" in text: subtype = "lick_mat"
    elif "desk mat" in text or "desk pad" in text or "mouse pad" in text or "mousepad" in text:
        subtype = "rgb_electronic_mat" if "rgb_electronic" in features else "leather_desk_mat" if material in {"leather", "cork"} or "pu leather" in text else "fabric_desk_mat" if "fabric_surface" in features or material in {"felt", "fabric", "cloth"} else "hard_desk_pad"
    if subtype == "pet_feeding_mat" and pack is None and not any(term in text for term in (" set", "bundle", "pair", "pcs", "pieces", "pack")):
        pack = 1
    return {"pack_count": pack, "size_class": size_class, "dimensions": dimensions, "positioning": positioning, "material": material or "UNKNOWN", "major_feature_set": features, "product_subtype": subtype, "brand_tier": brand_tier, "bundle_configuration": f"{pack}-piece" if pack else "UNKNOWN", "desk_sized": _desk_sized(dimensions, text)}


def classify_commercial_segment(result: dict[str, Any], profile: TargetCommercialProfile) -> dict[str, Any]:
    attrs = derive_segment_attributes(result); reasons: list[str] = []
    subtype = attrs["product_subtype"]; features = set(attrs["major_feature_set"]); pack = attrs["pack_count"]
    status = "UNKNOWN"
    if profile.product_subtype == "compression_packing_cubes":
        if subtype == "ordinary_packing_cubes": status, reasons = "NON_COMPARABLE", ["ordinary packing cubes are not the compression subtype"]
        elif subtype == "single_bag": status, reasons = "ADJACENT", ["single/unspecified bag is outside the target 4–8-piece set"]
        elif subtype != "compression_packing_cubes": status, reasons = "UNKNOWN", ["compression-cube subtype could not be established"]
        elif pack is None: status, reasons = "ADJACENT", ["compression product is relevant but pack count is unknown"]
        elif pack in profile.allowed_pack_counts: status, reasons = "COMPARABLE", [f"compression set pack count {pack} is within target 4–8"]
        else: status, reasons = "NON_COMPARABLE", [f"pack count {pack} is outside target 4–8 configuration"]
    elif profile.product_subtype == "fabric_desk_mat":
        if subtype in profile.excluded_subtypes: status, reasons = "NON_COMPARABLE", [f"{subtype} is outside the target fabric desk-mat segment"]
        elif subtype != "fabric_desk_mat": status, reasons = "UNKNOWN", ["fabric surface could not be established"]
        elif attrs["desk_sized"] is not True: status, reasons = "ADJACENT", ["desk-size format could not be established"]
        elif attrs["brand_tier"] == "PREMIUM_BRAND": status, reasons = "ADJACENT", ["premium branded listing is market context, not the target mid-market segment"]
        else: status, reasons = "COMPARABLE", ["fabric surface and desk-size format match the target commercial profile"]
    elif profile.product_subtype == "pet_feeding_mat":
        if subtype in profile.excluded_subtypes: status, reasons = "NON_COMPARABLE", [f"{subtype} is not a feeding-mat substitute"]
        elif subtype != "pet_feeding_mat": status, reasons = "UNKNOWN", ["feeding-mat subtype could not be established"]
        elif not profile.specific: status, reasons = "COMPARABLE", ["broad feeding-mat profile has no explicit size/pack segment constraint"]
        elif pack not in {None, 1}: status, reasons = "NON_COMPARABLE", [f"pack count {pack} differs from the target single mat"]
        elif "raised_edge" not in features: status, reasons = "ADJACENT", ["raised-edge feature is not established"]
        elif attrs["size_class"] not in {"LARGE", "XL"}: status, reasons = "ADJACENT", ["large/XL size is not established"]
        elif pack is None: status, reasons = "ADJACENT", ["single-pack configuration is not established"]
        else: status, reasons = "COMPARABLE", ["single large/XL raised-edge feeding mat matches target profile"]
    else:
        status, reasons = "COMPARABLE", ["broad target has no explicit commercial-segment constraint"]
    return {**attrs, "commercial_segment_status": status, "commercial_segment_reasons": reasons, "commercial_segment_rule_version": "v1.2.2"}
