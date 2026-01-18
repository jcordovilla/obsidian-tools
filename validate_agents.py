#!/usr/bin/env python3
"""
Validate Claude Code agents and skills in an Obsidian vault.

Checks for:
- Valid YAML frontmatter parsing
- Required fields (name, description)
- Single-line description format (critical for Claude Code)
- Model validity (sonnet, opus, haiku)
- Skill file existence for referenced skills
- Examples in correct format

Usage:
    python validate_agents.py --vault /path/to/vault
    python validate_agents.py  # Uses default JC vault
"""

import argparse
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationResult:
    """Result of validating a single agent/skill file."""
    path: Path
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    name: Optional[str] = None
    file_type: str = "agent"  # "agent" or "skill"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body) or ({}, content) if no frontmatter.
    """
    if not content.startswith('---'):
        return {}, content

    # Find closing ---
    lines = content.split('\n')
    end_index = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end_index = i
            break

    if end_index is None:
        return {}, content

    frontmatter_lines = lines[1:end_index]
    body = '\n'.join(lines[end_index + 1:])

    # Simple YAML parsing (handles our specific format)
    fm = {}
    current_key = None
    current_value = []
    in_multiline = False

    for line in frontmatter_lines:
        # Check for key: value
        if not in_multiline and ':' in line:
            # Save previous key if exists
            if current_key and current_value:
                fm[current_key] = '\n'.join(current_value).strip()

            parts = line.split(':', 1)
            key = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ''

            # Check for multiline indicator
            if value == '|' or value == '>':
                in_multiline = True
                current_key = key
                current_value = []
            elif value.startswith('"') or value.startswith("'"):
                # Quoted string - extract content
                current_key = key
                # Handle escaped quotes and newlines
                current_value = [value.strip('"').strip("'")]
                in_multiline = False
            else:
                current_key = key
                current_value = [value] if value else []
                in_multiline = False
        elif in_multiline:
            current_value.append(line)
        elif current_key and line.startswith('  '):
            # Continuation of previous value
            current_value.append(line.strip())

    # Save last key
    if current_key and current_value:
        fm[current_key] = '\n'.join(current_value).strip()

    return fm, body


def validate_agent(path: Path) -> ValidationResult:
    """Validate a single agent file."""
    result = ValidationResult(path=path, file_type="agent")

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        result.valid = False
        result.errors.append(f"Cannot read file: {e}")
        return result

    # Pre-parse check: look for common YAML errors in raw content
    # This catches issues before the parser might misinterpret them
    if content.startswith('---'):
        lines = content.split('\n')
        in_frontmatter = True
        found_desc = False
        desc_line_num = 0

        for i, line in enumerate(lines[1:], start=2):
            if line.strip() == '---':
                break

            # Check for description field
            if line.startswith('description:'):
                found_desc = True
                desc_line_num = i
                value = line.split(':', 1)[1].strip()

                # If description value doesn't start with quote and isn't a block scalar
                if value and not value.startswith('"') and not value.startswith("'") and value not in ('|', '>'):
                    # Check if next non-empty line looks like continuation (not a new key)
                    for j in range(i, min(i + 5, len(lines))):
                        next_line = lines[j] if j < len(lines) else ''
                        if next_line.strip() == '---':
                            break
                        if next_line.strip() and not next_line.startswith('  ') and ':' not in next_line:
                            # This looks like a broken multi-line description
                            result.valid = False
                            result.errors.append(
                                f"CRITICAL: Description appears to have unquoted multi-line content "
                                f"starting at line {desc_line_num}. Use quoted string with \\n escapes "
                                f"or YAML block scalar (description: |). Multi-line descriptions "
                                f"break Claude Code agent discovery."
                            )
                            break

    # Parse frontmatter
    fm, body = parse_frontmatter(content)

    if not fm:
        result.valid = False
        result.errors.append("No YAML frontmatter found (must start with ---)")
        return result

    # Check required fields
    if 'name' not in fm:
        result.valid = False
        result.errors.append("Missing required field: name")
    else:
        result.name = fm['name']

    if 'description' not in fm:
        result.valid = False
        result.errors.append("Missing required field: description")
    else:
        desc = fm['description']

        # Critical check: description must be single-line with \n escapes
        # Multi-line descriptions break the Task tool parser
        if '\n' in desc and '\\n' not in desc:
            result.valid = False
            result.errors.append(
                "CRITICAL: Description contains literal newlines. "
                "Must be single-line with \\n escapes. "
                "Multi-line descriptions break Claude Code discovery."
            )

        # Check for examples (recommended)
        if '<example>' not in desc.replace('\\n', '\n'):
            result.warnings.append(
                "Description has no <example> blocks. "
                "Examples improve agent discoverability."
            )

    # Validate model if specified
    if 'model' in fm:
        valid_models = ['sonnet', 'opus', 'haiku']
        if fm['model'] not in valid_models:
            result.valid = False
            result.errors.append(
                f"Invalid model: {fm['model']}. "
                f"Must be one of: {', '.join(valid_models)}"
            )
    else:
        result.warnings.append("No model specified (will use default)")

    # Check for skills reference
    if 'skills' in fm:
        skills = [s.strip() for s in fm['skills'].split(',')]
        vault_path = path.parents[2]  # .claude/agents/file.md -> vault
        skills_dir = vault_path / '.claude' / 'skills'

        for skill in skills:
            skill_path = skills_dir / skill
            skill_file = skills_dir / f"{skill}.md"
            skill_folder = skills_dir / skill / 'SKILL.md'

            if not (skill_file.exists() or skill_folder.exists()):
                result.warnings.append(
                    f"Referenced skill '{skill}' not found in .claude/skills/"
                )

    # Check body has content
    if not body.strip():
        result.warnings.append("Agent body is empty (no instructions after frontmatter)")

    return result


def validate_skill(path: Path) -> ValidationResult:
    """Validate a single skill file (SKILL.md)."""
    result = ValidationResult(path=path, file_type="skill")

    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        result.valid = False
        result.errors.append(f"Cannot read file: {e}")
        return result

    # Parse frontmatter
    fm, body = parse_frontmatter(content)

    if not fm:
        result.valid = False
        result.errors.append("No YAML frontmatter found")
        return result

    # Check required fields
    if 'name' not in fm:
        result.valid = False
        result.errors.append("Missing required field: name")
    else:
        result.name = fm['name']

    if 'description' not in fm:
        result.valid = False
        result.errors.append("Missing required field: description")

    # Check body has content
    if not body.strip():
        result.warnings.append("Skill body is empty")

    return result


def find_agents(vault_path: Path) -> list[Path]:
    """Find all agent files in the vault."""
    agents_dir = vault_path / '.claude' / 'agents'
    if not agents_dir.exists():
        return []
    return list(agents_dir.glob('*.md'))


def find_skills(vault_path: Path) -> list[Path]:
    """Find all skill files in the vault."""
    skills_dir = vault_path / '.claude' / 'skills'
    if not skills_dir.exists():
        return []

    skills = []
    # Direct .md files
    skills.extend(skills_dir.glob('*.md'))
    # SKILL.md in subdirectories
    skills.extend(skills_dir.glob('*/SKILL.md'))

    return skills


def print_results(results: list[ValidationResult]) -> int:
    """Print validation results and return exit code."""
    agents = [r for r in results if r.file_type == "agent"]
    skills = [r for r in results if r.file_type == "skill"]

    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)

    print(f"\n{'='*60}")
    print(f"Agent/Skill Validation Report")
    print(f"{'='*60}\n")

    # Agents section
    print(f"## Agents ({len(agents)} files)\n")
    for r in agents:
        status = "✓" if r.valid else "✗"
        name = r.name or r.path.stem
        print(f"  {status} {name}")

        for err in r.errors:
            print(f"      ERROR: {err}")
        for warn in r.warnings:
            print(f"      WARN:  {warn}")

    # Skills section
    print(f"\n## Skills ({len(skills)} files)\n")
    for r in skills:
        status = "✓" if r.valid else "✗"
        name = r.name or r.path.stem
        print(f"  {status} {name}")

        for err in r.errors:
            print(f"      ERROR: {err}")
        for warn in r.warnings:
            print(f"      WARN:  {warn}")

    # Summary
    print(f"\n{'='*60}")
    valid_count = sum(1 for r in results if r.valid)
    print(f"Summary: {valid_count}/{len(results)} valid")
    print(f"         {total_errors} errors, {total_warnings} warnings")
    print(f"{'='*60}\n")

    return 0 if total_errors == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Validate Claude Code agents and skills"
    )
    parser.add_argument(
        '--vault', '-v',
        type=Path,
        default=Path('/Users/jose/obsidian/JC'),
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )
    parser.add_argument(
        '--agents-only',
        action='store_true',
        help='Only validate agents, skip skills'
    )
    parser.add_argument(
        '--skills-only',
        action='store_true',
        help='Only validate skills, skip agents'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Only show errors and warnings, not passing validations'
    )

    args = parser.parse_args()

    if not args.vault.exists():
        print(f"Error: Vault path does not exist: {args.vault}")
        sys.exit(1)

    results = []

    # Validate agents
    if not args.skills_only:
        agent_files = find_agents(args.vault)
        for path in sorted(agent_files):
            results.append(validate_agent(path))

    # Validate skills
    if not args.agents_only:
        skill_files = find_skills(args.vault)
        for path in sorted(skill_files):
            results.append(validate_skill(path))

    if not results:
        print("No agents or skills found to validate.")
        sys.exit(0)

    exit_code = print_results(results)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
