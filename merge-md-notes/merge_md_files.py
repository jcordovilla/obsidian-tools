import os
from tkinter import Tk, filedialog, messagebox

# Hide the main tkinter window
root = Tk()
root.withdraw()

# Ask user to select multiple markdown files
file_paths = filedialog.askopenfilenames(
    title="Select Markdown files to merge",
    message="Select the markdown files you want to merge into a single document:",
    filetypes=[("Markdown files", "*.md")]
)

if not file_paths:
    messagebox.showinfo("No files selected", "No files were selected. Exiting.")
    exit()

# Read and concatenate contents with clear separators
merged_content = ""
for i, path in enumerate(file_paths, 1):
    # Add clear separator header for each file
    filename = os.path.basename(path)
    separator = f"\n{'='*80}\n"
    file_header = f"SOURCE FILE {i}: {filename}\n"
    file_path_info = f"File Path: {path}\n"
    file_separator = f"{'='*80}\n\n"
    
    # Read file content
    with open(path, 'r', encoding='utf-8') as f:
        file_content = f.read()
    
    # Add file separator and content
    merged_content += separator + file_header + file_path_info + file_separator + file_content
    
    # Add footer separator (except for the last file)
    if i < len(file_paths):
        merged_content += f"\n\n{'='*80}\nEND OF FILE: {filename}\n{'='*80}\n\n"

# Save merged file in the same directory as the first selected file
output_dir = os.path.dirname(file_paths[0])
output_path = os.path.join(output_dir, "merged.md")

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(merged_content)

messagebox.showinfo("Success", f"Merged file saved as: {output_path}")
