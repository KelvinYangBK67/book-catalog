"""Generate the book-catalog Web font adapter from the IMPE font catalog.

The generated files are committed so the application remains usable without
an IMPE checkout.  Font binaries are never copied into this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPE_ROOT = ROOT.parent / "IMPE"
OUTPUT_DIR = ROOT / "static" / "generated"

ROLE_FIELDS = {
    "serif": "regular",
    "sans": "sans",
    "bold": "bold",
}

# Metadata normally has no say in font selection: Unicode ranges select the
# concrete face character by character.  Mongolian and Manchu are the sole
# exceptions because they share the Mongolian block but require different
# shaping fonts.  The style values deliberately override catalog sans faces.
METADATA_OVERRIDES = {
    "mongolian": {
        "family": "mongolian_baiti",
        "aliases": ("mongolian", "蒙古文", "蒙文", "ᠮᠣᠩᠭᠣᠯ"),
        "styles": {"serif": "regular", "sans": "regular", "bold": "regular"},
    },
    "manchu": {
        "family": "manchu",
        "aliases": ("manchu", "滿文", "满文"),
        "styles": {"serif": "regular", "sans": "regular", "bold": "bold"},
    },
}

# Libertinus covers all three alphabetic profiles in each display role.
AGGREGATE_PROFILE_EXTENSIONS = {"latin": ("greek", "cyrillic")}

# A profile can have several catalog families.  This list selects the
# application default by IMPE family id only; no face name is duplicated here.
PROFILE_DEFAULTS = {
    "latin": "libertinus",
    "cjk-tc": "shanggu",
    "cjk-sc": "chinese_simplified",
    "cjk-jp": "japanese",
    "cjk-kr": "korean",
    "devanagari": "devanagari",
    "mongolian": "mongolian_baiti",
}

MONGOLIAN_OVERRIDE_RANGES = ("U+200C-200D", "U+202F")

# Libertinus is registered by installed font name in IMPE.  The Web adapter
# uses the equivalent locally cached files; all other faces resolve directly
# through \CatalogFontRoot.
LIBERTINUS_WEB_FILES = {
    "regular": "/static/fonts/web/LibertinusSerif-Regular.woff2",
    "bold": "/static/fonts/web/LibertinusSerif-Bold.woff2",
    "italic": "/static/fonts/web/LibertinusSerif-Italic.woff2",
    "bolditalic": "/static/fonts/web/LibertinusSerif-BoldItalic.woff2",
    "sans": "/static/fonts/libertinus/LibertinusSans-Regular.otf",
    "sansbold": "/static/fonts/libertinus/LibertinusSans-Bold.otf",
}

CUSTOM_BLOCKS = {
    "DevanagariPreMarks": (0x0900, 0x0950),
    "DevanagariMarks": (0x0951, 0x0954),
    "DevanagariPostMarks": (0x0955, 0x0963),
    "DevanagariDanDa": (0x0964, 0x0965),
    "DevanagariPostDanDa": (0x0966, 0x097F),
}


def strip_comments(source: str) -> str:
    return "\n".join(line.split("%", 1)[0] for line in source.splitlines())


def extract_calls(source: str, command: str) -> list[str]:
    marker = chr(92) + command
    result: list[str] = []
    offset = 0
    while True:
        start = source.find(marker, offset)
        if start < 0:
            return result
        brace = source.find("{", start + len(marker))
        if brace < 0:
            return result
        depth = 0
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    result.append(source[brace + 1:index])
                    offset = index + 1
                    break
        else:
            raise ValueError(f"Unclosed {command} declaration")


def split_top_level(value: str, separator: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def unwrap(value: str) -> str:
    value = value.strip()
    while value.startswith("{") and value.endswith("}"):
        depth = 0
        balanced = True
        for index, character in enumerate(value):
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        value = value[1:-1].strip()
    return re.sub(r"\s+", " ", value)


def parse_mapping(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in split_top_level(value):
        if "=" not in item:
            continue
        key, raw = item.split("=", 1)
        result[key.strip()] = unwrap(raw)
    return result


def parse_range_profiles(source: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    keys: dict[str, list[str]] = {}
    for command in ("DeclareRangeKey",):
        marker = chr(92) + command
        for line in strip_comments(source).splitlines():
            match = re.search(re.escape(marker) + r"\{([^}]+)\}\{([^}]+)\}", line)
            if match:
                keys[match.group(1)] = [part.strip() for part in match.group(2).split(",")]
    for line in strip_comments(source).splitlines():
        match = re.search(
            r'\\DeclareRangeCodepointKey\{([^}]+)\}\{["]?([0-9A-Fa-f]+)\}\{["]?([0-9A-Fa-f]+)\}',
            line,
        )
        if match:
            keys[match.group(1)] = [f"U+{match.group(2)}-{match.group(3)}"]
    profiles: dict[str, list[str]] = {}
    for line in strip_comments(source).splitlines():
        match = re.search(r"\\DeclareRangeProfile\{([^}]+)\}\{([^}]+)\}", line)
        if match:
            blocks: list[str] = []
            for key in (part.strip() for part in match.group(2).split(",")):
                blocks.extend(keys[key])
            profiles[match.group(1)] = blocks
    return keys, profiles


def parse_catalog(source: str) -> list[dict[str, object]]:
    families: list[dict[str, object]] = []
    for declaration in extract_calls(strip_comments(source), "FontRegisterFamily"):
        outer = parse_mapping(declaration)
        family_id = outer.get("id", "")
        if not family_id:
            continue
        local = parse_mapping(outer.get("local", "")) if "local" in outer else {}
        global_values = parse_mapping(outer.get("global", "")) if "global" in outer else {}
        selected = local or global_values
        families.append({
            "id": family_id,
            "defaultmode": outer.get("defaultmode", "local"),
            "rangeprofile": outer.get("rangeprofile", ""),
            "local": local,
            "global": global_values,
            "selected": selected,
        })
    return families


def style_key(value: str) -> str:
    return value.replace("_", "")


def parse_style_fallbacks(source: str) -> dict[str, str]:
    """Extract the direct fallback edges declared by IMPE core."""
    body = source[source.index(r"\cs_new_protected:Npn \__font_resolve_style_fallbacks:"):]
    body = body[:body.index(r"\cs_new_protected:Npn \__font_resolve_path_fallbacks:", 1)
                if r"\cs_new_protected:Npn \__font_resolve_path_fallbacks:" in body[1:]
                else len(body)]
    rules: dict[str, str] = {}
    pattern = re.compile(
        r"\\__font_resolve_field:NN\s+"
        r"\\l__font_resolved_([a-z_]+)_tl\s+"
        r"\\l__font_(?:resolved_)?([a-z_]+)_tl"
    )
    for target, fallback in pattern.findall(body):
        rules[style_key(target)] = style_key(fallback)
    required = {
        "bold": "regular",
        "italic": "regular",
        "sans": "regular",
        "sansbold": "sans",
        "mono": "regular",
        "monobold": "mono",
    }
    if any(rules.get(key) != value for key, value in required.items()):
        raise ValueError("IMPE style fallback rules changed; update the Web adapter.")
    return rules


def resolve_styles(
    values: dict[str, str], fallback_rules: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve IMPE styles at generation time and retain each face source."""
    if not values.get("regular"):
        return {}, {}
    source: dict[str, str] = {"regular": "regular"}
    faces: dict[str, str] = {"regular": values["regular"]}

    def use(target: str, candidates: Iterable[str]) -> None:
        for candidate in candidates:
            if values.get(candidate):
                faces[target] = values[candidate]
                source[target] = candidate
                return
            if candidate in faces:
                faces[target] = faces[candidate]
                source[target] = source[candidate]
                return

    use("bold", ("bold", fallback_rules["bold"]))
    use("italic", ("italic", fallback_rules["italic"]))
    if values.get("bolditalic"):
        use("bolditalic", ("bolditalic",))
    elif values.get("italic"):
        use("bolditalic", ("italic",))
    elif values.get("bold"):
        use("bolditalic", ("bold",))
    else:
        use("bolditalic", ("regular",))
    use("sans", ("sans", fallback_rules["sans"]))
    use("sansbold", ("sansbold", fallback_rules["sansbold"]))
    if values.get("sansitalic"):
        use("sansitalic", ("sansitalic",))
    elif values.get("sans"):
        use("sansitalic", ("sans",))
    else:
        use("sansitalic", ("italic",))
    if values.get("sansbolditalic"):
        use("sansbolditalic", ("sansbolditalic",))
    elif values.get("sansbold"):
        use("sansbolditalic", ("sansbold",))
    else:
        use("sansbolditalic", ("sansitalic",))
    use("mono", ("mono", fallback_rules["mono"]))
    use("monobold", ("monobold", fallback_rules["monobold"]))
    return faces, source


def catalog_path(value: str) -> str:
    match = re.search(r"\\CatalogFontRoot/([^/]+)/?", value or "")
    return match.group(1) if match else ""


def face_url(
    family_id: str,
    values: dict[str, str],
    faces: dict[str, str],
    face_sources: dict[str, str],
    style: str,
) -> str:
    if family_id == "libertinus":
        source_style = face_sources[style]
        return LIBERTINUS_WEB_FILES.get(style, LIBERTINUS_WEB_FILES.get(source_style, ""))
    source_style = face_sources[style]
    directory = catalog_path(
        values.get(source_style + "path", "") or values.get("path", "")
    )
    face = faces.get(style, "")
    return f"/fonts/{directory}/{face}" if directory and face else ""


def normalize_block_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def unicode_block_map() -> dict[str, tuple[int, int]]:
    try:
        from fontTools.unicodedata import Blocks
    except ImportError as error:
        raise SystemExit(
            "Generating CSS unicode ranges requires fontTools "
            "(python -m pip install fonttools)."
        ) from error
    result: dict[str, tuple[int, int]] = {}
    for index, (start, name) in enumerate(zip(Blocks.RANGES, Blocks.VALUES)):
        end = Blocks.RANGES[index + 1] - 1 if index + 1 < len(Blocks.RANGES) else 0x10FFFF
        result[normalize_block_name(name)] = (start, end)
    result.update({normalize_block_name(key): value for key, value in CUSTOM_BLOCKS.items()})
    return result


def ranges_for_profile(blocks: list[str], block_map: dict[str, tuple[int, int]]) -> list[str]:
    ranges: list[str] = []
    for block in blocks:
        if block.startswith("U+"):
            ranges.append(block.upper())
            continue
        value = block_map.get(normalize_block_name(block))
        if not value:
            raise ValueError(f"Unknown Unicode block from IMPE range profile: {block}")
        start, end = value
        ranges.append(f"U+{start:04X}-{end:04X}")
    return ranges


def infer_profile(family_id: str, declared: str, profiles: dict[str, list[str]]) -> str:
    if declared:
        return declared
    normalized = family_id.replace("_", "-")
    if normalized in profiles:
        return normalized
    for profile in profiles:
        if normalized in profile or profile in normalized:
            return profile
    return ""


def css_format(url: str) -> str:
    suffix = Path(url).suffix.lower()
    return {".woff2": "woff2", ".otf": "opentype", ".ttf": "truetype"}.get(suffix, "")


def css_face(name: str, url: str, weight: str, ranges: list[str] | None = None) -> str:
    range_part = f" unicode-range: {', '.join(ranges)};" if ranges else ""
    return (
        f'@font-face {{ font-family: "{name}"; src: url("{url}") '
        f'format("{css_format(url)}"); font-weight: {weight}; font-style: normal; '
        f"font-display: swap;{range_part} }}"
    )


def build(impe_root: Path) -> tuple[str, dict[str, object], str]:
    catalog_file = impe_root / "catalog" / "fonts.tex"
    range_file = impe_root / "catalog" / "fonts" / "range-profiles.tex"
    style_file = impe_root / "core" / "fonts" / "style.tex"
    sources = [catalog_file, range_file, style_file]
    for source in sources:
        if not source.is_file():
            raise SystemExit(f"Required IMPE source is missing: {source}")

    catalog_source = catalog_file.read_text(encoding="utf-8")
    _, profiles = parse_range_profiles(range_file.read_text(encoding="utf-8"))
    fallback_rules = parse_style_fallbacks(style_file.read_text(encoding="utf-8"))
    families = parse_catalog(catalog_source)
    block_map = unicode_block_map()

    records: dict[str, dict[str, object]] = {}
    for family in families:
        family_id = str(family["id"])
        values = dict(family["selected"])
        faces, face_sources = resolve_styles(values, fallback_rules)
        if not faces:
            continue
        urls = {
            style: face_url(family_id, values, faces, face_sources, style)
            for style in faces
        }
        if not urls.get("regular"):
            continue
        profile = infer_profile(
            family_id, str(family["rangeprofile"]), profiles
        )
        records[family_id] = {
            "id": family_id,
            "profile": profile,
            "script": values.get("script", ""),
            "language": values.get("language", ""),
            "script_class": values.get("scriptclass", ""),
            "layout": values.get("layout", ""),
            "faces": faces,
            "face_sources": face_sources,
            "urls": urls,
        }

    route_family_ids: dict[str, str] = {}
    absorbed_profiles = {
        extension
        for extensions in AGGREGATE_PROFILE_EXTENSIONS.values()
        for extension in extensions
    }
    for profile in profiles:
        if profile in absorbed_profiles:
            continue
        preferred = PROFILE_DEFAULTS.get(profile)
        candidates = [
            family_id for family_id, record in records.items()
            if record["profile"] == profile
        ]
        if preferred in candidates:
            route_family_ids[profile] = preferred
        elif profile in candidates:
            route_family_ids[profile] = profile
        elif candidates:
            route_family_ids[profile] = candidates[0]
    route_family_ids["latin"] = "libertinus"

    aliases: dict[str, str] = {}
    for route, override in METADATA_OVERRIDES.items():
        family_id = str(override["family"])
        if family_id not in records:
            raise ValueError(f"Missing metadata override family: {family_id}")
        for label in override["aliases"]:
            aliases[str(label).casefold()] = route

    css_lines = [
        "/* GENERATED FILE — DO NOT EDIT.",
        " * Source: IMPE catalog/fonts.tex, range-profiles.tex, core/fonts/style.tex",
        " * Rebuild: python scripts/generate_web_fonts.py",
        " */",
        "",
    ]
    override_ranges = ranges_for_profile(profiles["mongolian"], block_map)
    override_ranges.extend(MONGOLIAN_OVERRIDE_RANGES)
    for route, override in METADATA_OVERRIDES.items():
        record = records[str(override["family"])]
        for role, style in override["styles"].items():
            url = record["urls"].get(str(style), "")
            if url:
                css_lines.append(css_face(
                    f"IMPE Override {route} {str(role).title()}",
                    url,
                    "400",
                    override_ranges,
                ))
    css_lines.append("")

    emitted_range_signatures: set[tuple[str, ...]] = set()
    for profile, family_id in route_family_ids.items():
        if family_id not in records or profile not in profiles:
            continue
        profile_blocks = list(profiles[profile])
        for extension in AGGREGATE_PROFILE_EXTENSIONS.get(profile, ()):
            profile_blocks.extend(profiles[extension])
        ranges = ranges_for_profile(profile_blocks, block_map)
        signature = tuple(ranges)
        if signature in emitted_range_signatures:
            continue
        emitted_range_signatures.add(signature)
        record = records[family_id]
        for role, style in ROLE_FIELDS.items():
            url = record["urls"].get(style, "")
            if url:
                css_lines.append(css_face(f"Library {role.title()}", url, "400", ranges))
        sans_bold = record["urls"].get("sansbold", "")
        if sans_bold:
            css_lines.append(css_face("Library Sans", sans_bold, "600 900", ranges))
    css_lines.extend([
        "",
        ':root { --font-sans: "Library Sans", "Segoe UI", sans-serif;',
        '  --font-serif: "Library Serif", "Times New Roman", serif;',
        '  --font-bold: "Library Bold", "Times New Roman", serif; }',
        '.font-sans { font-family: var(--font-sans); }',
        '.font-serif { font-family: var(--font-serif); }',
        '.font-bold { font-family: var(--font-bold); font-weight: 400; }',
    ])
    for route in METADATA_OVERRIDES:
        for role in ROLE_FIELDS:
            css_lines.append(
                f'.font-{role}[data-font-route="{route}"] '
                f'{{ font-family: "IMPE Override {route} {role.title()}", var(--font-{role}); }}'
            )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "generated_from": {
            source.relative_to(impe_root).as_posix(): hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
            for source in sources
        },
        "style_fallback_source": "core/fonts/style.tex",
        "style_fallbacks": fallback_rules,
        "roles": ROLE_FIELDS,
        "profiles": profiles,
        "profile_defaults": route_family_ids,
        "aggregate_profile_extensions": AGGREGATE_PROFILE_EXTENSIONS,
        "metadata_overrides": METADATA_OVERRIDES,
        "aliases": dict(sorted(aliases.items())),
        "families": records,
    }
    routes_js = (
        "/* GENERATED FILE — DO NOT EDIT.\n"
        " * Rebuild: python scripts/generate_web_fonts.py\n"
        " */\n"
        f"export const FONT_ROUTE_ALIASES = Object.freeze({json.dumps(manifest['aliases'], ensure_ascii=False, indent=2)});\n"
        "export function resolveCatalogFontRoute(value) {\n"
        "  const terms = String(value || '').split(/[;；,，、·]/).map((item) => item.trim().toLocaleLowerCase()).filter(Boolean);\n"
        "  for (const term of terms) {\n"
        "    if (FONT_ROUTE_ALIASES[term]) return FONT_ROUTE_ALIASES[term].replaceAll('_', '-');\n"
        "  }\n"
        "  return '';\n"
        "}\n"
    )
    return "\n".join(css_lines) + "\n", manifest, routes_js


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--impe-root",
        type=Path,
        default=Path(os.getenv("IMPE_ROOT", DEFAULT_IMPE_ROOT)),
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    css, manifest, routes_js = build(args.impe_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "fonts.css").write_text(css, encoding="utf-8", newline="\n")
    (args.output_dir / "font-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (args.output_dir / "font-routes.js").write_text(
        routes_js, encoding="utf-8", newline="\n"
    )
    print(f"Generated {len(manifest['families'])} IMPE Web font families.")


if __name__ == "__main__":
    main()
