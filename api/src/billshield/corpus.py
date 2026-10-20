"""Activate byte-authenticated official legal text with exact page quotations.

The MVP automatically verifies text and source hashes; this is not professional
legal review. Source completeness and currentness remain explicit.
"""

import hashlib
import json
import re
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from billshield.engine import (
    MVP_START,
    Citation,
    CodeEntry,
    Condition,
    Corpus,
    Coverage,
    LegalRule,
    RateEntry,
    SourceDocument,
)

CHAPTERS = ("15", "17", "19", "21", "25", "30", "33", "34")
SECTIONS = {
    "15": "III",
    "17": "IV",
    "19": "IV",
    "21": "IV",
    "25": "V",
    "30": "VI",
    "33": "VI",
    "34": "VI",
}


def _digest(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _official(url):
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and parts.port in (None, 443)
        and (
            (parts.hostname or "").endswith((".gov.in", ".nic.in"))
            or (
                (parts.hostname or "") == "www.wcoomd.org"
                and parts.path.startswith(
                    "/-/media/wco/public/global/pdf/topics/nomenclature/instruments-and-tools/hs-nomenclature-2022/2022/"
                )
                and "/explanatory" not in parts.path.lower()
            )
        )
    )


def corpus_from_verified_pages(verification: dict, snapshot_id: str) -> Corpus:
    """Assemble output from the original-file verifier or snapshot loader.

    Caller must first verify original bytes using ingest_m2.verify_manifest or
    use load_snapshot below. Page hashes are rechecked at this boundary.
    """
    sources = {}
    aliases = {}
    for item in sorted(verification["accepted"], key=lambda entry: entry["id"]):
        source = item["source"]
        if not _official(source["url"]):
            raise ValueError("Nonofficial source in verified corpus")
        pages = {}
        for page in item["pages"]:
            text = page["text_original"]
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != page["text_sha256"]:
                raise ValueError("Canonical source page hash mismatch")
            pages[page["source_page"]] = text
        kind = source["document_type"]
        source_id = source["source_key"]
        sources[source_id] = SourceDocument(
            source_id,
            pages,
            date.fromisoformat(source["issued_on"]) if source.get("issued_on") else None,
            verified=True,
            official=True,
            kind="customs_tariff" if kind in ("customs_tariff", "tariff_chapter") else kind,
            sha256=source["content_sha256"],
        )
        aliases[item["id"]] = source_id
        if item.get("scope", {}).get("chapter") and kind in (
            "customs_tariff",
            "tariff_chapter",
            "hs_chapter",
        ):
            aliases[f"hs_tariff_{item['scope']['chapter']}"] = source_id
        if item.get("scope", {}).get("section") and kind == "section_notes":
            aliases[f"hs_section_{item['scope']['section']}"] = source_id
        if item.get("scope", {}).get("chapter") and kind in ("customs_tariff", "tariff_chapter"):
            aliases[f"national_tariff_{item['scope']['chapter']}"] = source_id
        if item.get("scope", {}).get("section") and kind == "section_notes":
            aliases[f"national_section_{item['scope']['section']}"] = source_id
        if kind == "gri":
            aliases["national_gri"] = source_id
        if kind == "hs_contents":
            for section in ("III", "V"):
                if any(
                    re.search(rf"(?m)^SECTION {section}\s*$", p["text_original"])
                    for p in item["pages"]
                ):
                    aliases[f"hs_section_{section}"] = source_id
    rules, codes, rates, mandatory = activate_pages(verification, sources)
    checklist = {}
    for chapter in CHAPTERS:
        # HS4/6 evidence is sufficient unless the selected GST rate requires a
        # national eight-digit item. Each chapter keeps an explicit checklist.
        names = (
            f"hs_tariff_{chapter}",
            "national_gri",
            f"hs_section_{SECTIONS[chapter]}",
            "cgst_09_2025",
            "cgst_10_2025",
            "goa_09_2025",
            "goa_10_2025",
        )
        if chapter == "33":
            names += ("mcnroe",)
        checklist[chapter] = tuple(aliases.get(name, name) for name in names)
    return Corpus(
        snapshot_id,
        sources,
        rules,
        codes,
        rates,
        tuple(
            Coverage(ch, "Goa", MVP_START, complete=False, verified_through=None) for ch in CHAPTERS
        ),
        required_source_ids=checklist,
        mandatory_rule_ids=mandatory,
        # The cross-chapter boundary map remains explicit even while evidence is absent.
        rival_chapters={
            "17": ("21",),
            "19": ("21",),
            "21": ("17", "19"),
            "25": ("34",),
            "30": ("33",),
            "33": ("30",),
            "34": ("25",),
        },
    )


def _citation(source_id, page, quote):
    return Citation(source_id=source_id, page=page, quote=quote)


def _date(item):
    value = item["source"].get("issued_on")
    return date.fromisoformat(value) if value else None


def _numbered_notes(text):
    """Return complete literal note spans, never confuse a page with a note.

    A final note without a following note or explicit table boundary may run
    onto the next page; leave that note available only in full page material.
    """
    boundary = re.search(r"(?m)^[ \t]*(?:Heading\b|_{3,})", text)
    end = boundary.start() if boundary else len(text)
    matches = list(re.finditer(r"(?m)^[ \t]*(\d+)\s*\.\s*[-–]", text[:end]))
    for index, match in enumerate(matches):
        if index + 1 < len(matches):
            finish = matches[index + 1].start()
        elif boundary:
            finish = end
        else:
            continue
        yield match[1], text[match.start() : finish]


def activate_pages(verification, sources):
    """Activate reproducible selectors only from authenticated canonical pages.

    This is automatic text verification, not professional legal review. Full
    notes remain mandatory and unchanged; no fixture identifier or expected
    verdict participates. Rates come from each notification's schedule heading.
    """
    rules, codes, rates = {}, {}, {}
    mandatory = {chapter: [] for chapter in CHAPTERS}
    all_chapters = tuple(CHAPTERS)
    for item in sorted(verification["accepted"], key=lambda entry: entry["id"]):
        kind = item["source"]["document_type"]
        sid = item["source"]["source_key"]
        chapter = item.get("scope", {}).get("chapter")
        section = item.get("scope", {}).get("section")
        start = _date(item)
        if not start:
            continue
        scopes = (chapter,) if chapter else tuple(ch for ch in CHAPTERS if SECTIONS[ch] == section)
        if kind == "hs_contents":
            # III and V have no section notes in the official HS contents.
            # Quote the actual complete section block; never fabricate a note.
            for section in ("III", "V"):
                for page in item["pages"]:
                    match = re.search(
                        rf"(?ms)^SECTION {section}\s*$.*?(?=^SECTION [IVX]+\s*$|\Z)",
                        page["text_original"],
                    )
                    if not match or re.search(r"Section Notes?\.", match[0], re.I):
                        continue
                    section_chapters = tuple(ch for ch in CHAPTERS if SECTIONS[ch] == section)
                    rid = f"{item['id']}:section_structure:{section}"
                    rules[rid] = LegalRule(
                        rid,
                        "section_note",
                        _citation(sid, page["source_page"], match[0]),
                        start,
                        chapters=section_chapters,
                        reviewed=True,
                        status="no_section_notes_in_official_contents",
                        auto_verified=True,
                    )
                    for ch in section_chapters:
                        mandatory[ch].append(rid)
        if item["id"] == "mcnroe":
            # Persuasive reasoning is available without pretending an AAR binds
            # unrelated suppliers. Never promote its quoted national items.
            for page in item["pages"]:
                if page["source_page"] < 9 or not page["text_original"].strip():
                    continue
                rid = f"mcnroe:persuasive:{page['source_page']}"
                rules[rid] = LegalRule(
                    rid,
                    "persuasive_ruling",
                    _citation(sid, page["source_page"], page["text_original"]),
                    start,
                    chapters=("33",),
                    reviewed=True,
                    status="persuasive_party_specific",
                    supports_codes=("3307", "330710"),
                    auto_verified=True,
                )
                mandatory["33"].append(rid)
        if kind == "gri":
            # A GRI source must actually contain all six numbered rules. Each
            # rule quotes its whole page, retaining every qualification.
            found = {}
            for page in item["pages"]:
                for number in range(1, 7):
                    if re.search(rf"(?m)^\s*{number}[.)]\s", page["text_original"]):
                        found[number] = page
            if set(found) == set(range(1, 7)):
                for number, page in found.items():
                    rid = f"{item['id']}:gri_{number}"
                    rules[rid] = LegalRule(
                        rid,
                        f"gri_{number}",
                        _citation(sid, page["source_page"], page["text_original"]),
                        start,
                        chapters=all_chapters,
                        reviewed=True,
                        auto_verified=True,
                    )
                    for ch in CHAPTERS:
                        mandatory[ch].append(rid)
        if kind in ("customs_tariff", "tariff_chapter", "hs_chapter", "section_notes") and scopes:
            for page in item["pages"]:
                text = page["text_original"]
                if not text.strip():
                    continue  # Genuine blank layout pages contain no rule text.
                note_kind = "section_note" if kind == "section_notes" else "chapter_note"
                page_kind = "section_page" if kind == "section_notes" else "chapter_page"
                rid = f"{item['id']}:{page_kind}:{page['source_page']}"
                citation = _citation(sid, page["source_page"], text)
                rules[rid] = LegalRule(
                    rid,
                    note_kind,
                    citation,
                    start,
                    chapters=scopes,
                    reviewed=True,
                    auto_verified=True,
                )
                for ch in scopes:
                    mandatory[ch].append(rid)
                for number, quote in _numbered_notes(text):
                    note_id = f"{item['id']}:{note_kind}:{number}"
                    # Repeated numbering across layout regions is ambiguous.
                    # Full canonical pages remain mandatory in every case.
                    if note_id in rules:
                        continue
                    rules[note_id] = LegalRule(
                        note_id,
                        note_kind,
                        _citation(sid, page["source_page"], quote),
                        start,
                        chapters=scopes,
                        reviewed=True,
                        auto_verified=True,
                    )
                if not chapter:
                    continue
                found_codes = set()
                # Only literal printed HS heading/subheading cells are loaded.
                for match in re.finditer(r"(?m)^\s*(\d{2})\.(\d{2})\s", text):
                    found_codes.add(match[1] + match[2])
                for match in re.finditer(r"(?m)^\s*(\d{4})\.(\d{2})\s", text):
                    found_codes.add(match[1] + match[2])
                national = kind in ("customs_tariff", "tariff_chapter")
                if national:
                    for match in re.finditer(
                        r"(?m)^\s*(\d{4})(?:[ \t]+(\d{2})(?:[ \t]+(\d{2}))?)?[ \t]+", text
                    ):
                        found_codes.add("".join(x or "" for x in match.groups()))
                for code in sorted(found_codes):
                    if not code.startswith(chapter):
                        continue
                    # Prefer national evidence if two authenticated texts overlap.
                    if code not in codes or national:
                        codes[code] = CodeEntry(
                            code, citation, start, authenticated_national=national
                        )
                    rid = f"{item['id']}:heading:{code}"
                    rules[rid] = LegalRule(
                        rid,
                        "heading",
                        citation,
                        start,
                        chapters=(chapter,),
                        reviewed=True,
                        supports_codes=(code,),
                        auto_verified=True,
                    )
                    mandatory[chapter].append(rid)
        if item["id"] in ("cgst_09_2025", "cgst_10_2025", "goa_09_2025", "goa_10_2025"):
            component = "CGST" if item["id"].startswith("cgst") else "SGST"
            jurisdiction = "India" if component == "CGST" else "Goa"
            exemption = "10_2025" in item["id"]
            current_schedule, rate = None, None
            full_text = "\n".join(p["text_original"] for p in item["pages"])
            if "22" not in full_text or "2025" not in full_text:
                continue
            if exemption and not re.search(
                r"from the whole of (?:the )?(?:State|central) tax", full_text, re.I
            ):
                continue
            for page in item["pages"]:
                text = page["text_original"]
                # Schedule headings and following rows retain their byte-bound
                # exact page quotations; the numeric rate never comes from a model.
                events = [
                    (m.start(), "schedule", m)
                    for m in re.finditer(
                        r"Schedule\s+([IVX]+)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*%", text, re.I
                    )
                ]
                events += [
                    (m.start(), "row", m)
                    for m in re.finditer(
                        r"(?m)^\s*(\d+)\.[ \t]+(1513|1704|1905|3004|3307|3401|2501)[ \t]+([^\n]+)",
                        text,
                    )
                ]
                for _, event, match in sorted(events, key=lambda x: x[0]):
                    if event == "schedule":
                        current_schedule, rate = match[1].upper(), Decimal(match[2])
                        rid = f"{item['id']}:rate_basis:{current_schedule}"
                        rules[rid] = LegalRule(
                            rid,
                            "rate_basis",
                            _citation(sid, page["source_page"], text),
                            MVP_START,
                            chapters=all_chapters,
                            reviewed=True,
                            auto_verified=True,
                        )
                        continue
                    if not exemption and (current_schedule is None or rate is None):
                        continue
                    end = re.search(
                        r"(?m)^\s*\d+\.[ \t]+(?:\d{2,8}|Any chapter)\b"
                        r"|^\d{4}\s*$|^OFFICIAL GAZETTE",
                        text[match.end() :],
                    )
                    quote = text[match.start() : match.end() + end.start() if end else len(text)]
                    prefix = match[2]
                    description = quote.casefold()
                    normalized = re.sub(r"\s+", " ", description)
                    allowed = {
                        "1513": "coconut",
                        "1704": "sugar confection",
                        "1905": "pastry",
                        "3004": "medicaments",
                        "2501": "salt",
                        "3307": "shav",
                        "3401": "soap",
                    }
                    if allowed[prefix] not in normalized:
                        continue
                    conditions = ()
                    if prefix == "3307":
                        if "pre-shave" in normalized or "pre-shave" in normalized.replace(" ", ""):
                            conditions = (
                                Condition("use", "shav", "contains"),
                                Condition("form", "foam", "contains"),
                                Condition("form", "cream", "not_contains"),
                                Condition("form", "lotion", "not_contains"),
                            )
                        else:
                            # The named concession includes creams and lotions;
                            # branch alternatives remain separate selectors.
                            conditions = (
                                Condition("use", "shav", "contains"),
                                Condition("form", "cream", "contains"),
                            )
                    if prefix == "3401":
                        if "organic surface" in normalized:
                            conditions = (
                                Condition("form", "soap", "contains"),
                                Condition("use", "washing clothes", "contains"),
                            )
                        else:
                            conditions = (
                                Condition("use", "toilet", "contains"),
                                Condition("form", "bar", "contains"),
                            )
                    if prefix == "3004":
                        conditions = (
                            Condition("medicinal_licence", True),
                            Condition("use", "therapeut", "contains"),
                            Condition("form", "retail", "contains"),
                        )
                    schedule_id = "exempt" if exemption else current_schedule
                    entry = f"{item['id']}:{schedule_id}:{match[1]}:{prefix}"
                    if not exemption:
                        mandatory[prefix[:2]].append(f"{item['id']}:rate_basis:{current_schedule}")
                    rates[entry] = RateEntry(
                        entry,
                        prefix,
                        component,
                        jurisdiction,
                        Decimal(0) if exemption else rate,
                        _citation(sid, page["source_page"], quote),
                        MVP_START,
                        conditions=conditions,
                        reviewed=True,
                        auto_verified=True,
                    )
                    if prefix == "3401" and "organic surface" in normalized:
                        # Positive branches prove the intended non-toilet use or
                        # liquid skin-washing form; absence of 'toilet' proves nothing.
                        rates[entry] = replace(rates[entry], entry_id=entry + ":laundry")
                        rates[entry + ":laundry"] = rates.pop(entry)
                        liquid_id = entry + ":liquid_skin"
                        rates[liquid_id] = replace(
                            rates[entry + ":laundry"],
                            entry_id=liquid_id,
                            conditions=(
                                Condition("form", "liquid", "contains"),
                                Condition("use", "washing skin", "contains"),
                            ),
                        )
            if exemption:
                rid = f"{item['id']}:exemption_basis"
                first = next(
                    p
                    for p in item["pages"]
                    if re.search(
                        r"from the whole of (?:the )?(?:State|central) tax",
                        p["text_original"],
                        re.I,
                    )
                )
                rules[rid] = LegalRule(
                    rid,
                    "rate_basis",
                    _citation(sid, first["source_page"], first["text_original"]),
                    MVP_START,
                    chapters=all_chapters,
                    reviewed=True,
                    auto_verified=True,
                )
                for ch in CHAPTERS:
                    mandatory[ch].append(rid)
    return rules, codes, rates, {ch: tuple(dict.fromkeys(ids)) for ch, ids in mandatory.items()}


def activation_manifest(corpus):
    """Hash every executable record including selectors and canonical quotes."""

    def records(values):
        return {key: _digest(asdict(value)) for key, value in sorted(values.items())}

    return {
        "policy": "auto-verified, not professionally reviewed",
        "rules": records(corpus.rules),
        "codes": records(corpus.codes),
        "rates": records(corpus.rates),
        "mandatory_rule_ids": {k: list(v) for k, v in corpus.mandatory_rule_ids.items()},
    }


def load_snapshot(connection, snapshot_id: str) -> Corpus:
    """Load immutable verified M2 canonical pages through a runtime DB connection.

    Neither legacy HSN rows nor unreviewed historical rates are activated. The
    snapshot manifest and page membership hashes fence post-issuance mutation.
    """
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        snapshot = cursor.execute(
            "SELECT content_sha256,manifest_json FROM billshield.law_snapshots WHERE id=%s",
            (snapshot_id,),
        ).fetchone()
        if not snapshot or _digest(snapshot["manifest_json"]) != snapshot["content_sha256"]:
            raise ValueError("Missing or altered law snapshot")
        manifest = snapshot["manifest_json"]
        if manifest.get("importer_version") not in ("m2-browser-pages-v1", "m2-auto-pages-v3"):
            raise ValueError("Snapshot has no verified M2 canonical pages")
        keys = [item["source"]["source_key"] for item in manifest["sources"]]
        documents = {
            row["source_key"]: row
            for row in cursor.execute(
                "SELECT * FROM billshield.source_documents WHERE source_key=ANY(%s)", (keys,)
            ).fetchall()
        }
        canonical_pages = {
            (row["source_key"], row["source_page"]): row
            for row in cursor.execute(
                "SELECT source_key,source_page,text_original,text_sha256 "
                "FROM billshield.source_pages WHERE source_key=ANY(%s)",
                (keys,),
            ).fetchall()
        }
        members = {
            row["record_id"]: row["record_sha256"]
            for row in cursor.execute(
                "SELECT record_id,record_sha256 FROM billshield.law_snapshot_members "
                "WHERE snapshot_id=%s AND kind='source_pages'",
                (snapshot_id,),
            ).fetchall()
        }
        accepted = []
        for item in manifest["sources"]:
            expected_source = item["source"]
            source_key = expected_source["source_key"]
            row = documents.get(source_key)
            if row is None:
                raise ValueError("Missing snapshot source")
            normalized = {
                key: (row[key].isoformat() if hasattr(row[key], "isoformat") else row[key])
                for key in expected_source
            }
            if normalized != expected_source:
                raise ValueError("Altered snapshot source")
            pages = []
            for expected_page in item["pages"]:
                page = canonical_pages.get((source_key, expected_page["source_page"]))
                member = members.get(f"{source_key}|{expected_page['source_page']}")
                if (
                    not page
                    or not member
                    or _digest(dict(page)) != member
                    or page["text_sha256"] != expected_page["text_sha256"]
                ):
                    raise ValueError("Missing or altered snapshot page")
                pages.append(dict(page))
            accepted.append(
                {
                    "id": item["id"],
                    "source": expected_source,
                    "scope": item["scope"],
                    "pages": pages,
                }
            )
    corpus = corpus_from_verified_pages({"accepted": accepted}, snapshot_id)
    if manifest.get("importer_version") == "m2-auto-pages-v3" and manifest.get(
        "activation"
    ) != activation_manifest(corpus):
        raise ValueError("Missing or altered activated legal records")
    if manifest.get("importer_version") == "m2-browser-pages-v1":
        return replace(corpus, rules={}, codes={}, rates={}, mandatory_rule_ids={})
    return corpus
