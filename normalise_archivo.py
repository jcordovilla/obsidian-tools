#!/usr/bin/env python3
"""
Batch normalise notes in 4.ARCHIVO/ folder without frontmatter.
Adds proper YAML frontmatter with tags, language detection, and reflection sections.
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Optional

# Vault path
VAULT_PATH = Path("/Users/jose/obsidian/JC")
ARCHIVO_PATH = VAULT_PATH / "4.ARCHIVO"

# Approved tags
APPROVED_TYPES = {
    "type/note", "type/article", "type/book", "type/reference",
    "type/chatgpt-conversation", "type/idea", "type/meeting", "type/project",
    "type/course", "type/moc"
}

APPROVED_TOPICS = {
    # Infrastructure & PPP
    "topic/ppp", "topic/project-finance", "topic/infrastructure-delivery",
    "topic/asset-management", "topic/value-for-money", "topic/concessions",
    "topic/fiscal-management", "topic/risk-allocation", "topic/procurement",
    "topic/construction",
    # Risk & Resilience
    "topic/risk", "topic/resilience", "topic/climate-risk",
    "topic/operational-risk", "topic/demand-risk",
    # Sectors
    "topic/transport", "topic/roads", "topic/rail", "topic/water",
    "topic/energy", "topic/digital-infrastructure",
    # Policy & Governance
    "topic/governance", "topic/policy", "topic/regulation",
    "topic/transparency", "topic/public-sector",
    # Digital & AI
    "topic/ai", "topic/ml", "topic/data", "topic/digital-transformation",
    "topic/digital-twins", "topic/automation",
    # Sustainability
    "topic/sustainability", "topic/climate-adaptation", "topic/green-finance"
}

APPROVED_SOURCES = {
    "source/own-writing", "source/chatgpt", "source/web",
    "source/book", "source/pdf", "source/course", "source/linkedin",
    "source/meeting"
}

APPROVED_STATUS = {
    "status/idea", "status/outline", "status/draft", "status/review",
    "status/published", "status/active", "status/paused", "status/archived",
    "status/expanded"
}

APPROVED_CONTEXT = {
    "context/typsa", "context/spain", "context/africa", "context/ireland",
    "context/latam", "context/europe"
}

APPROVED_LANGS = {
    "lang/en", "lang/es"
}


def detect_language(text: str) -> str:
    """Detect if content is primarily Spanish or English."""
    if not text:
        return "lang/en"

    # Spanish indicators
    spanish_words = {
        "de", "la", "el", "que", "en", "con", "los", "las", "para",
        "por", "una", "del", "como", "es", "una", "el", "su", "este",
        "ese", "cual", "esos", "estas", "esos", "esas", "quisiera",
        "sería", "podría", "debería", "necesita", "necesario", "importante",
        "objetivo", "objetivo", "estructura", "función", "arquitectura"
    }

    # Spanish accented characters
    spanish_accents = r"[áéíóúñüÁÉÍÓÚÑÜ]"

    # Sample first 2000 chars
    sample = text[:2000].lower()

    # Count Spanish word matches
    spanish_count = sum(1 for word in spanish_words if f" {word} " in f" {sample} ")

    # Count accented characters
    accent_count = len(re.findall(spanish_accents, sample))

    # Check for Spanish punctuation
    spanish_punct = len(re.findall(r"[¿¡]", sample))

    # Decision: if strong Spanish signals, return ES
    if accent_count >= 3 or spanish_count >= 5 or spanish_punct > 0:
        return "lang/es"

    return "lang/en"


def detect_content_type_and_topics(filename: str, content: str) -> Tuple[str, List[str]]:
    """
    Detect content type and appropriate topics from filename and content.
    Returns tuple of (type_tag, [topic_tags])
    """
    filename_lower = filename.lower()
    content_lower = content[:2000].lower()

    topics = []
    content_type = "type/note"  # default

    # Filename-based detection
    if "chatgpt" in filename_lower or "gpt" in filename_lower:
        content_type = "type/chatgpt-conversation"
        topics.append("topic/ai")
    elif any(x in filename_lower for x in ["curso", "course", "blockchain", "training"]):
        content_type = "type/course"
    elif any(x in filename_lower for x in ["conference", "evento", "rail live", "dakar"]):
        content_type = "type/meeting"
    elif "idea" in filename_lower:
        content_type = "type/idea"
    elif any(x in filename_lower for x in ["press", "news", "prensa", "bloomberg", "ijglobal"]):
        # Press clippings should still get proper tagging
        content_type = "type/article"
    elif any(x in filename_lower for x in ["arquitectura", "instruction", "instruccion", "proyecto"]):
        content_type = "type/project"

    # Content-based topic detection

    # PPP/Infrastructure topics
    if any(x in content_lower for x in ["ppp", "concession", "public private partnership", "arrendamiento"]):
        topics.append("topic/ppp")
    if any(x in content_lower for x in ["risk", "riesgo", "allocation", "asignación"]):
        topics.append("topic/risk")
    if any(x in content_lower for x in ["rail", "railway", "ferrocarril", "ffcc"]):
        topics.append("topic/rail")
    if any(x in content_lower for x in ["road", "carretera", "toll", "peaje"]):
        topics.append("topic/roads")
    if any(x in content_lower for x in ["water", "agua", "wtp", "saneamiento"]):
        topics.append("topic/water")
    if any(x in content_lower for x in ["energy", "energía", "renewable", "solar"]):
        topics.append("topic/energy")
    if any(x in content_lower for x in ["governance", "gobernanza", "policy", "política"]):
        topics.append("topic/governance")
    if any(x in content_lower for x in ["resilience", "resiliencia", "climate", "clima"]):
        topics.append("topic/resilience")
    if any(x in content_lower for x in ["digital", "ai", "artificial", "ia", "inteligencia"]):
        if "topic/ai" not in topics:
            topics.append("topic/ai")
    if any(x in content_lower for x in ["asset", "maintenance", "mantenimiento", "activo"]):
        topics.append("topic/asset-management")
    if any(x in content_lower for x in ["finance", "financing", "financiamiento", "inversión"]):
        topics.append("topic/project-finance")

    # Remove duplicates
    topics = list(set(topics))

    # If no topics detected, don't force any
    if not topics:
        topics = []

    return content_type, topics


def has_frontmatter(file_path: Path) -> bool:
    """Check if file already has frontmatter."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            return first_line == "---"
    except Exception:
        return False


def read_file(file_path: Path) -> Optional[str]:
    """Read file content safely."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"  ERROR reading: {e}")
        return None


def estimate_usefulness(filename: str, content: str, content_type: str) -> float:
    """Estimate usefulness score (0.0-1.0)."""
    score = 0.5  # default

    # Press clippings: lower value
    if any(x in filename.lower() for x in ["prensa", "press", "news", "bloomberg"]):
        score = 0.35

    # ChatGPT conversations: higher value
    if "chatgpt" in filename.lower() or "gpt" in filename.lower():
        score = 0.65

    # Projects/technical: higher value
    if "proyecto" in filename.lower() or "architecture" in filename.lower():
        score = 0.70

    # Takeaways/meeting notes: moderate-high
    if "takeaway" in filename.lower() or "evento" in filename.lower():
        score = 0.65

    # Length adjustment
    if len(content) > 5000:
        score += 0.15
    elif len(content) < 500:
        score -= 0.15

    # Structure adjustment (if it has sections)
    if content.count("\n## ") > 2:
        score += 0.10

    # Cap between 0.3 and 0.9
    return max(0.3, min(0.9, score))


def create_frontmatter(filename: str, content: str) -> str:
    """Create YAML frontmatter for the note."""

    # Detect language
    lang = detect_language(content)

    # Detect type and topics
    content_type, topics = detect_content_type_and_topics(filename, content)

    # Build tag list
    tags = [content_type, lang, "status/archived"]

    # Add topics
    tags.extend(topics)

    # Remove duplicates, sort
    tags = sorted(list(set(tags)))

    # Estimate usefulness
    usefulness = estimate_usefulness(filename, content, content_type)

    # Create frontmatter
    date_str = datetime.now().strftime("%Y-%m-%d")

    yaml_tags = "  - " + "\n  - ".join(tags)

    frontmatter = f"""---
date: "{date_str}"
tags:
{yaml_tags}
usefulness: {usefulness:.1f}
---
"""

    return frontmatter


def add_reflection_sections(content: str) -> str:
    """Add My Thoughts and Related Notes sections if not present."""

    # Check if sections already exist
    if "## My Thoughts" in content or "# My Thoughts" in content:
        return content  # Already has reflection sections

    reflection = """
## My Thoughts

*Add your thoughts here*

## Related Notes

*No related notes identified*

---

"""

    return reflection + content


def normalise_file(file_path: Path) -> Tuple[bool, str]:
    """
    Normalise a single file. Returns (success, message).
    """
    filename = file_path.name

    # Skip if already has frontmatter
    if has_frontmatter(file_path):
        return False, "Already normalised"

    # Read content
    content = read_file(file_path)
    if content is None:
        return False, "Could not read file"

    # Create frontmatter
    frontmatter = create_frontmatter(filename, content)

    # Add reflection sections
    content_with_sections = add_reflection_sections(content)

    # Combine
    new_content = frontmatter + content_with_sections

    # Write back
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True, "Normalised"
    except Exception as e:
        return False, f"Write error: {e}"


def main():
    """Main batch processing function."""

    if not ARCHIVO_PATH.exists():
        print(f"ERROR: Archive folder not found at {ARCHIVO_PATH}")
        sys.exit(1)

    # Find all .md files
    all_files = sorted(ARCHIVO_PATH.rglob("*.md"))

    # Filter to only those without frontmatter
    needs_normalisation = [f for f in all_files if not has_frontmatter(f)]

    print(f"\n📊 **Batch Normalisation: 4.ARCHIVO/\n")
    print(f"Total .md files: {len(all_files)}")
    print(f"Files without frontmatter: {len(needs_normalisation)}\n")

    # Process each file
    normalised = 0
    already_done = 0
    errors = []

    stats = {
        "type_tags": {},
        "topic_tags": {},
        "langs": {},
        "usefulness_scores": []
    }

    for i, file_path in enumerate(needs_normalisation, 1):
        rel_path = file_path.relative_to(ARCHIVO_PATH)

        success, message = normalise_file(file_path)

        if success:
            normalised += 1
            print(f"✓ [{i:2d}/{len(needs_normalisation)}] {rel_path}")

            # Collect stats
            content = read_file(file_path)
            if content:
                _, topics = detect_content_type_and_topics(file_path.name, content)
                lang = detect_language(content)
                score = estimate_usefulness(file_path.name, content, "")

                stats["langs"][lang] = stats["langs"].get(lang, 0) + 1
                stats["usefulness_scores"].append(score)

                for topic in topics:
                    stats["topic_tags"][topic] = stats["topic_tags"].get(topic, 0) + 1
        else:
            if message == "Already normalised":
                already_done += 1
            else:
                errors.append((rel_path, message))
                print(f"✗ [{i:2d}/{len(needs_normalisation)}] {rel_path} - {message}")

    # Summary report
    print(f"\n{'='*70}")
    print(f"\n📊 **Batch Processing Summary**\n")
    print(f"Normalised: {normalised} files")
    print(f"Already compliant: {already_done} files")
    print(f"Errors: {len(errors)} files\n")

    # Tag statistics
    print(f"Language distribution:")
    for lang, count in sorted(stats["langs"].items()):
        print(f"  {lang}: {count}")

    if stats["topic_tags"]:
        print(f"\nMost common topics:")
        top_topics = sorted(stats["topic_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
        for topic, count in top_topics:
            print(f"  {topic}: {count}")

    if stats["usefulness_scores"]:
        avg_score = sum(stats["usefulness_scores"]) / len(stats["usefulness_scores"])
        print(f"\nAverage usefulness score: {avg_score:.2f}")

    # Error details
    if errors:
        print(f"\nErrors encountered:")
        for path, msg in errors:
            print(f"  {path}: {msg}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
