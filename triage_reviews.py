#!/usr/bin/env python3
"""
Interactive GUI for triaging "review" conversations.

Displays each review case one at a time with key information and two buttons:
- KEEP: Change action to "keep"
- ARCHIVE: Change action to "archive"

Updates the JSON report file on the go.
"""

import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path
from typing import List, Dict
import sys
import re


class TriageApp:
    def __init__(self, root, report_path: Path):
        self.root = root
        self.report_path = report_path
        self.root.title("ChatGPT Conversation Triage")
        self.root.geometry("1100x900")

        # Load data
        self.load_data()

        # Current index
        self.current_idx = 0

        # Setup UI
        self.setup_ui()

        # Show first conversation
        self.show_current()

    def load_data(self):
        """Load the JSON report and filter for review cases."""
        with open(self.report_path, 'r') as f:
            self.all_data = json.load(f)

        # Filter for review cases only
        self.review_cases = [
            conv for conv in self.all_data
            if conv['analysis']['suggested_action'] == 'review'
        ]

        print(f"Loaded {len(self.review_cases)} review cases from {len(self.all_data)} total conversations")

    def extract_chat_preview(self, file_path: Path, max_chars: int = 3000) -> str:
        """Extract a preview of the chat content from the markdown file."""
        try:
            content = file_path.read_text(encoding='utf-8')

            # Remove the title (first line with #)
            content = re.sub(r'^#\s+.+\n', '', content, count=1)

            # Extract first few exchanges to get a feel for the conversation
            # Look for user/assistant message patterns
            preview_lines = []
            current_chars = 0

            for line in content.split('\n'):
                if current_chars >= max_chars:
                    preview_lines.append("\n[... conversation continues ...]")
                    break

                preview_lines.append(line)
                current_chars += len(line) + 1

            return '\n'.join(preview_lines)

        except Exception as e:
            return f"[Error reading file: {e}]"

    def setup_ui(self):
        """Create the UI layout."""
        # Progress bar at top
        self.progress_frame = ttk.Frame(self.root, padding="10")
        self.progress_frame.pack(fill=tk.X)

        self.progress_label = ttk.Label(
            self.progress_frame,
            text="",
            font=('Arial', 12, 'bold')
        )
        self.progress_label.pack()

        # Main content frame
        self.content_frame = ttk.Frame(self.root, padding="10")
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        self.title_label = ttk.Label(
            self.content_frame,
            text="",
            font=('Arial', 14, 'bold'),
            wraplength=1050
        )
        self.title_label.pack(pady=(0, 10))

        # Metadata frame
        self.meta_frame = ttk.Frame(self.content_frame)
        self.meta_frame.pack(fill=tk.X, pady=(0, 10))

        # Score
        self.score_label = ttk.Label(
            self.meta_frame,
            text="",
            font=('Arial', 11, 'bold')
        )
        self.score_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 20))

        # Framework
        self.framework_label = ttk.Label(
            self.meta_frame,
            text="",
            font=('Arial', 11)
        )
        self.framework_label.grid(row=0, column=1, sticky=tk.W)

        # Topics
        ttk.Label(self.meta_frame, text="Topics:", font=('Arial', 10, 'bold')).grid(
            row=1, column=0, sticky=tk.W, pady=(5, 0)
        )
        self.topics_label = ttk.Label(
            self.meta_frame,
            text="",
            font=('Arial', 10),
            wraplength=1050
        )
        self.topics_label.grid(row=2, column=0, columnspan=2, sticky=tk.W)

        # Separator
        ttk.Separator(self.content_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        # Reasoning
        ttk.Label(
            self.content_frame,
            text="AI Reasoning:",
            font=('Arial', 10, 'bold')
        ).pack(anchor=tk.W)

        self.reasoning_text = scrolledtext.ScrolledText(
            self.content_frame,
            wrap=tk.WORD,
            height=5,
            font=('Arial', 10),
            bg='#f5f5f5'
        )
        self.reasoning_text.pack(fill=tk.X, pady=(5, 10))

        # Framework description (if exists)
        self.framework_frame = ttk.Frame(self.content_frame)
        self.framework_frame.pack(fill=tk.X, pady=(0, 10))

        self.framework_title = ttk.Label(
            self.framework_frame,
            text="Framework:",
            font=('Arial', 10, 'bold')
        )

        self.framework_text = scrolledtext.ScrolledText(
            self.framework_frame,
            wrap=tk.WORD,
            height=4,
            font=('Arial', 10),
            bg='#e8f4f8'
        )

        # Chat preview section
        ttk.Separator(self.content_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        ttk.Label(
            self.content_frame,
            text="Conversation Preview:",
            font=('Arial', 10, 'bold')
        ).pack(anchor=tk.W)

        self.chat_preview = scrolledtext.ScrolledText(
            self.content_frame,
            wrap=tk.WORD,
            height=12,
            font=('Courier', 9),
            bg='#fafafa'
        )
        self.chat_preview.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Button frame
        self.button_frame = ttk.Frame(self.root, padding="10")
        self.button_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # Navigation buttons
        self.prev_button = ttk.Button(
            self.button_frame,
            text="← Previous",
            command=self.prev_conversation
        )
        self.prev_button.pack(side=tk.LEFT, padx=5)

        self.next_button = ttk.Button(
            self.button_frame,
            text="Next →",
            command=self.next_conversation
        )
        self.next_button.pack(side=tk.LEFT, padx=5)

        # Spacer
        ttk.Frame(self.button_frame, width=50).pack(side=tk.LEFT)

        # Decision buttons
        self.archive_button = ttk.Button(
            self.button_frame,
            text="ARCHIVE",
            command=self.mark_archive,
            style='Archive.TButton'
        )
        self.archive_button.pack(side=tk.LEFT, padx=10, ipadx=20, ipady=10)

        self.keep_button = ttk.Button(
            self.button_frame,
            text="KEEP",
            command=self.mark_keep,
            style='Keep.TButton'
        )
        self.keep_button.pack(side=tk.LEFT, padx=10, ipadx=20, ipady=10)

        # Quit button
        ttk.Button(
            self.button_frame,
            text="Save & Quit",
            command=self.quit_app
        ).pack(side=tk.RIGHT, padx=5)

        # Setup button styles
        style = ttk.Style()
        style.configure('Keep.TButton', font=('Arial', 12, 'bold'))
        style.configure('Archive.TButton', font=('Arial', 12))

        # Keyboard shortcuts
        self.root.bind('<Left>', lambda e: self.prev_conversation())
        self.root.bind('<Right>', lambda e: self.next_conversation())
        self.root.bind('k', lambda e: self.mark_keep())
        self.root.bind('a', lambda e: self.mark_archive())
        self.root.bind('q', lambda e: self.quit_app())

    def show_current(self):
        """Display the current conversation."""
        if not self.review_cases:
            messagebox.showinfo("Complete", "All review cases have been triaged!")
            self.quit_app()
            return

        if self.current_idx >= len(self.review_cases):
            messagebox.showinfo("Complete", "You've reviewed all cases! Click 'Save & Quit' to finish.")
            return

        conv = self.review_cases[self.current_idx]
        analysis = conv['analysis']

        # Update progress
        remaining = sum(1 for c in self.review_cases if c['analysis']['suggested_action'] == 'review')
        reviewed = len(self.review_cases) - remaining
        self.progress_label.config(
            text=f"Progress: {reviewed}/{len(self.review_cases)} reviewed | "
                 f"Current: {self.current_idx + 1}/{len(self.review_cases)}"
        )

        # Update title
        title = conv['title'].replace('Title: ', '')
        filename = Path(conv['path']).name
        self.title_label.config(text=f"{title}\n({filename})")

        # Update score
        score = analysis['quality_score']
        score_color = 'green' if score >= 70 else 'orange' if score >= 50 else 'red'
        self.score_label.config(
            text=f"Score: {score}/100",
            foreground=score_color
        )

        # Update framework
        has_framework = analysis.get('has_framework', False)
        self.framework_label.config(
            text=f"Framework: {'✓ Yes' if has_framework else '✗ No'}",
            foreground='green' if has_framework else 'gray'
        )

        # Update topics
        topics = ', '.join(analysis.get('primary_topics', []))
        self.topics_label.config(text=topics)

        # Update reasoning
        self.reasoning_text.config(state='normal')
        self.reasoning_text.delete('1.0', tk.END)
        reasoning = analysis.get('reasoning', 'No reasoning provided.')
        self.reasoning_text.insert('1.0', reasoning)
        self.reasoning_text.config(state='disabled')

        # Update framework description if exists
        framework_desc = analysis.get('framework_description')
        if has_framework and framework_desc:
            self.framework_title.pack(anchor=tk.W)
            self.framework_text.pack(fill=tk.X, pady=(5, 0))
            self.framework_text.config(state='normal')
            self.framework_text.delete('1.0', tk.END)
            self.framework_text.insert('1.0', framework_desc)
            self.framework_text.config(state='disabled')
        else:
            self.framework_title.pack_forget()
            self.framework_text.pack_forget()

        # Update chat preview
        self.chat_preview.config(state='normal')
        self.chat_preview.delete('1.0', tk.END)
        chat_content = self.extract_chat_preview(Path(conv['path']))
        self.chat_preview.insert('1.0', chat_content)
        self.chat_preview.config(state='disabled')

        # Update button states
        self.prev_button.config(state='normal' if self.current_idx > 0 else 'disabled')

        # Highlight current decision if already made
        current_action = analysis['suggested_action']
        if current_action == 'keep':
            self.keep_button.config(style='Keep.TButton')
            self.archive_button.config(style='TButton')
        elif current_action == 'archive':
            self.archive_button.config(style='Archive.TButton')
            self.keep_button.config(style='TButton')
        else:
            self.keep_button.config(style='TButton')
            self.archive_button.config(style='TButton')

    def mark_keep(self):
        """Mark current conversation as keep."""
        self.update_decision('keep')
        self.next_conversation()

    def mark_archive(self):
        """Mark current conversation as archive."""
        self.update_decision('archive')
        self.next_conversation()

    def update_decision(self, action: str):
        """Update the decision for current conversation."""
        if self.current_idx >= len(self.review_cases):
            return

        conv = self.review_cases[self.current_idx]
        conv['analysis']['suggested_action'] = action

        # Find and update in all_data
        for i, c in enumerate(self.all_data):
            if c['path'] == conv['path']:
                self.all_data[i]['analysis']['suggested_action'] = action
                break

        # Save immediately
        self.save_data()

    def save_data(self):
        """Save the updated data to JSON file."""
        with open(self.report_path, 'w') as f:
            json.dump(self.all_data, f, indent=2)

    def next_conversation(self):
        """Move to next conversation."""
        if self.current_idx < len(self.review_cases) - 1:
            self.current_idx += 1
            self.show_current()

    def prev_conversation(self):
        """Move to previous conversation."""
        if self.current_idx > 0:
            self.current_idx -= 1
            self.show_current()

    def quit_app(self):
        """Save and quit the application."""
        self.save_data()

        # Show final stats
        stats = {
            'keep': sum(1 for c in self.all_data if c['analysis']['suggested_action'] == 'keep'),
            'archive': sum(1 for c in self.all_data if c['analysis']['suggested_action'] == 'archive'),
            'review': sum(1 for c in self.all_data if c['analysis']['suggested_action'] == 'review')
        }

        messagebox.showinfo(
            "Triage Complete",
            f"Final distribution:\n\n"
            f"Keep: {stats['keep']}\n"
            f"Archive: {stats['archive']}\n"
            f"Review: {stats['review']}\n\n"
            f"Report saved to:\n{self.report_path}"
        )

        self.root.quit()


def main():
    """Main entry point."""
    report_path = Path("/Users/jose/obsidian/chatgpt_analysis_report.json")

    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)

    root = tk.Tk()
    app = TriageApp(root, report_path)

    print("\n" + "="*80)
    print("TRIAGE APP CONTROLS:")
    print("="*80)
    print("  KEEP button (or 'k' key): Mark as keep and move to next")
    print("  ARCHIVE button (or 'a' key): Mark as archive and move to next")
    print("  ← → arrow keys: Navigate between conversations")
    print("  'q' key: Save and quit")
    print("="*80)
    print()

    root.mainloop()


if __name__ == '__main__':
    main()
