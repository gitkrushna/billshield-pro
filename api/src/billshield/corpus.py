"""Load authenticated M2 page evidence without activating unreviewed research.

Acquiring a PDF is distinct from reviewing its legal predicates. This loader
retains the source checklist and false coverage flags, but deliberately exposes
no executable rules, rates, or national items until a reviewed import exists.
"""

import hashlib
import json
from datetime import date
from urllib.parse import urlsplit

from billshield.engine import MVP_START, Corpus, Coverage, SourceDocument

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
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _official(url):
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and (parts.hostname or "").endswith((".gov.in", ".nic.in"))
    )


def corpus_from_verified_pages(verification: dict, snapshot_id: str) -> Corpus:
    """Assemble output from the original-file verifier or snapshot loader.

    Caller must first verify original bytes using ingest_m2.verify_manifest or
    use load_snapshot below. Page hashes are rechecked at this boundary.
    """
    sources = {}
    aliases = {}
    for item in verification["accepted"]:
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
        if item.get("scope", {}).get("chapter") and kind in ("customs_tariff", "tariff_chapter"):
            aliases[f"national_tariff_{item['scope']['chapter']}"] = source_id
        if item.get("scope", {}).get("section") and kind == "section_notes":
            aliases[f"national_section_{item['scope']['section']}"] = source_id
        if kind == "gri":
            aliases["national_gri"] = source_id
    checklist = {}
    for chapter in CHAPTERS:
        names = (
            f"national_tariff_{chapter}",
            "national_gri",
            f"national_section_{SECTIONS[chapter]}",
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
        {},
        {},
        {},
        tuple(
            Coverage(ch, "Goa", MVP_START, complete=False, verified_through=None) for ch in CHAPTERS
        ),
        required_source_ids=checklist,
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
        if manifest.get("importer_version") != "m2-browser-pages-v1":
            raise ValueError("Snapshot has no verified M2 canonical pages")
        accepted = []
        for item in manifest["sources"]:
            expected_source = item["source"]
            source_key = expected_source["source_key"]
            row = cursor.execute(
                "SELECT * FROM billshield.source_documents WHERE source_key=%s",
                (source_key,),
            ).fetchone()
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
                page = cursor.execute(
                    "SELECT source_key,source_page,text_original,text_sha256 "
                    "FROM billshield.source_pages WHERE source_key=%s AND source_page=%s",
                    (source_key, expected_page["source_page"]),
                ).fetchone()
                member = cursor.execute(
                    "SELECT record_sha256 FROM billshield.law_snapshot_members "
                    "WHERE snapshot_id=%s AND kind='source_pages' AND record_id=%s",
                    (snapshot_id, f"{source_key}|{expected_page['source_page']}"),
                ).fetchone()
                if (
                    not page
                    or not member
                    or _digest(dict(page)) != member["record_sha256"]
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
    return corpus_from_verified_pages({"accepted": accepted}, snapshot_id)
